import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


def find_dataset_path(explicit: str | None = None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise FileNotFoundError(f"Dataset not found: {p}")
        return p

    candidates = [
        Path("out") / "teams_full.csv",
        Path("out") / "teams_plus_more.csv",
        Path("out") / "teams_plus.csv",
        Path("out") / "teams.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No dataset CSV found in out/. Expected one of: teams_full.csv, teams_plus_more.csv, teams_plus.csv, teams.csv"
    )


def detect_target_column(df: pd.DataFrame) -> str | None:
    candidates = [
        "team100_win",
        "win_100",
        "blue_win",
        "win",
        "target",
        "y",
        "label",
        "result",
        "outcome",
    ]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def find_match_id_column(df: pd.DataFrame) -> str | None:
    candidates = ["match_id", "matchId", "gameId", "id", "matchid", "game_id"]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def load_model(model_path: str | None = None):
    mp = Path(model_path) if model_path else (Path("out") / "model_full_cv.joblib")
    if not mp.exists():
        raise FileNotFoundError(f"Missing model file: {mp}. Run: python train_full_cv.py")

    obj = joblib.load(mp)

    # Pipeline saved directly
    if hasattr(obj, "predict_proba"):
        return {"pipeline": obj, "num_feats": None, "cat_feats": None, "target": None}

    # Dict payload
    if isinstance(obj, dict) and "pipeline" in obj:
        return {
            "pipeline": obj["pipeline"],
            "num_feats": obj.get("num_feats"),
            "cat_feats": obj.get("cat_feats"),
            "target": obj.get("target"),
        }

    raise TypeError(f"Unsupported model format in {mp}: {type(obj)}")


def explain_logreg(pipe, X_one: pd.DataFrame, topk: int = 20):
    if "preprocess" not in pipe.named_steps or "clf" not in pipe.named_steps:
        print("\nEXPLAIN: pipeline does not have expected steps preprocess+clf")
        return

    clf = pipe.named_steps["clf"]
    if not hasattr(clf, "coef_"):
        print("\nEXPLAIN: classifier has no coef_")
        return

    preprocess = pipe.named_steps["preprocess"]
    try:
        names = preprocess.get_feature_names_out()
    except Exception:
        print("\nEXPLAIN: cannot get feature names from preprocess")
        return

    Xt = preprocess.transform(X_one)
    if hasattr(Xt, "toarray"):
        xvec = Xt.toarray()[0]
    else:
        xvec = np.asarray(Xt)[0]

    coefs = clf.coef_[0]
    intercept = float(clf.intercept_[0]) if hasattr(clf, "intercept_") else 0.0

    contrib = xvec * coefs
    order = np.argsort(np.abs(contrib))[::-1]

    print("\nEXPLAIN (log-odds contributions; + pushes class 1, - pushes class 0)")
    print(f"intercept: {intercept:+.6f}")

    shown = 0
    for idx in order:
        if shown >= topk:
            break
        val = contrib[idx]
        if not np.isfinite(val) or abs(val) < 1e-12:
            continue
        print(f"{val:+.6f}  {names[idx]}")
        shown += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", default=None, help="Match/game id to score (optional)")
    ap.add_argument("--dataset", default=None, help="Path to dataset CSV (default: auto from out/)")
    ap.add_argument("--model", default=None, help="Path to model joblib (default: out/model_full_cv.joblib)")
    ap.add_argument("--explain", action="store_true", help="Print top feature contributions for the selected match")
    ap.add_argument("--topk", type=int, default=20, help="Top K contributions to print with --explain")
    args = ap.parse_args()

    model = load_model(args.model)
    pipe = model["pipeline"]
    num_feats = model["num_feats"]
    cat_feats = model["cat_feats"]
    saved_target = model["target"]

    dataset_path = find_dataset_path(args.dataset)
    df = pd.read_csv(dataset_path, low_memory=False)

    target_col = saved_target if (saved_target in df.columns) else detect_target_column(df)

    # feature columns must match training
    if isinstance(num_feats, list) and isinstance(cat_feats, list) and (len(num_feats) + len(cat_feats) > 0):
        feat_cols = num_feats + cat_feats
        missing = [c for c in feat_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Dataset is missing feature columns required by saved model: {missing}")
    else:
        # fallback: use all columns except target
        feat_cols = [c for c in df.columns if c != target_col]

    id_col = find_match_id_column(df)

    # select row
    if args.match_id is not None and id_col is not None:
        want = str(args.match_id)
        series = df[id_col].astype(str)
        hits = df[series == want]
        if hits.empty:
            sample = df[id_col].astype(str).head(20).tolist()
            raise ValueError(f"Match id '{want}' not found in column '{id_col}'. Sample ids: {sample}")
        row = hits.iloc[0:1].copy()
    else:
        row = df.iloc[-1:].copy()

    X = row[feat_cols]

    # predict
    proba = None
    if hasattr(pipe, "predict_proba"):
        probs = pipe.predict_proba(X)[0]
        classes = list(pipe.classes_)
        if 1 in classes:
            proba = float(probs[classes.index(1)])
        else:
            proba = float(probs[0])

    pred = int(pipe.predict(X)[0])

    # output
    if id_col is not None and id_col in row.columns:
        print(f"match_id: {row.iloc[0][id_col]}")

    print(f"predicted_class: {pred}")
    if proba is not None:
        print(f"probability_class_1: {proba:.6f}")

    if target_col is not None and target_col in row.columns:
        try:
            actual = int(pd.to_numeric(row.iloc[0][target_col], errors="coerce"))
            if actual in (0, 1):
                print(f"actual: {actual}")
        except Exception:
            pass

    if args.explain:
        explain_logreg(pipe, X, topk=args.topk)


if __name__ == "__main__":
    main()