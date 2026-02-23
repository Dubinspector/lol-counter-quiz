import argparse
from pathlib import Path
from datetime import datetime

import joblib
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


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


def _is_binary_01(series: pd.Series) -> bool:
    s = pd.to_numeric(series, errors="coerce")
    u = set(s.dropna().unique().tolist())
    return len(u) > 0 and u.issubset({0, 1})


def _same_or_inverse_as_target(col: pd.Series, y: pd.Series) -> tuple[bool, str | None]:
    s = pd.to_numeric(col, errors="coerce")
    mask = ~s.isna() & ~y.isna()
    if mask.sum() == 0:
        return False, None
    s2 = s[mask].astype(int)
    y2 = y[mask].astype(int)
    if (s2.values == y2.values).all():
        return True, "identical_to_target"
    if (s2.values == (1 - y2.values)).all():
        return True, "inverse_of_target"
    return False, None


def _perfect_threshold_separation(col: pd.Series, y: pd.Series) -> bool:
    s = pd.to_numeric(col, errors="coerce")
    mask = ~s.isna() & ~y.isna()
    if mask.sum() == 0:
        return False
    s = s[mask]
    y = y[mask].astype(int)

    s0 = s[y == 0]
    s1 = s[y == 1]
    if len(s0) == 0 or len(s1) == 0:
        return False

    if s0.max() < s1.min():
        return True
    if s1.max() < s0.min():
        return True
    return False


def leak_name_based_drop(columns: list[str], target: str) -> tuple[list[str], dict[str, list[str]]]:
    reasons: dict[str, list[str]] = {
        "id_like": [],
        "outcome_like_name": [],
    }

    drop = set()

    id_tokens = [
        "match_id", "matchid", "gameid", "game_id", "id",
        "puuid", "summonerid", "accountid", "platformid",
    ]

    outcome_tokens = [
        "win", "winner", "victory", "result", "outcome", "label", "target",
    ]

    for c in columns:
        cl = c.lower()
        if c == target:
            continue

        if cl in id_tokens or cl.endswith("_id") or cl.endswith("id"):
            drop.add(c)
            reasons["id_like"].append(c)
            continue

        if any(tok in cl for tok in outcome_tokens):
            drop.add(c)
            reasons["outcome_like_name"].append(c)
            continue

    return sorted(drop), reasons


def build_pipeline(num_feats: list[str], cat_feats: list[str]) -> Pipeline:
    transformers = []

    if num_feats:
        num_pipe = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]
        )
        transformers.append(("num", num_pipe, num_feats))

    if cat_feats:
        cat_pipe = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore")),
            ]
        )
        transformers.append(("cat", cat_pipe, cat_feats))

    if not transformers:
        raise ValueError("No features left after dropping/leak filtering.")

    preprocess = ColumnTransformer(transformers=transformers, remainder="drop")

    clf = LogisticRegression(
        max_iter=8000,
        solver="saga",
        C=1.0,
    )

    return Pipeline(steps=[("preprocess", preprocess), ("clf", clf)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=None, help="Path to dataset CSV (default: auto from out/)")
    ap.add_argument("--target", default=None, help="Target column (default: auto-detect)")
    ap.add_argument("--model-out", default=str(Path("out") / "model_full_cv.joblib"))
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--audit-only", action="store_true", help="Only print leak audit results; do not train.")
    ap.add_argument("--cv", type=int, default=5)
    args = ap.parse_args()

    dataset_path = find_dataset_path(args.dataset)
    df = pd.read_csv(dataset_path, low_memory=False)

    target = args.target or detect_target_column(df)
    if not target:
        raise ValueError("Target column not found. Pass --target <col>.")
    if target not in df.columns:
        raise ValueError(f"Target '{target}' not in dataset columns.")

    y = pd.to_numeric(df[target], errors="coerce")
    df = df[~y.isna()].copy()
    y = y[~y.isna()].astype(int)
    if not set(y.unique().tolist()).issubset({0, 1}):
        raise ValueError(f"Target '{target}' is not binary 0/1. Unique: {sorted(set(y.unique().tolist()))}")

    drop1, _reasons1 = leak_name_based_drop(df.columns.tolist(), target=target)
    df2 = df.drop(columns=drop1, errors="ignore")

    drop2 = []
    drop2_reasons: dict[str, str] = {}

    feature_candidates = [c for c in df2.columns if c != target]
    for c in feature_candidates:
        s = df2[c]

        if _is_binary_01(s):
            is_leak, why = _same_or_inverse_as_target(s, y)
            if is_leak:
                drop2.append(c)
                drop2_reasons[c] = why or "same_or_inverse"
                continue

        if pd.api.types.is_numeric_dtype(s) or _is_binary_01(s):
            if _perfect_threshold_separation(s, y):
                drop2.append(c)
                drop2_reasons[c] = "perfect_threshold_separation"
                continue

        if pd.api.types.is_object_dtype(s) or isinstance(s.dtype, pd.CategoricalDtype) or pd.api.types.is_string_dtype(s):
            s3 = s.astype(str)
            cats0 = set(s3[y == 0].dropna().unique().tolist())
            cats1 = set(s3[y == 1].dropna().unique().tolist())
            if len(cats0) > 0 and len(cats1) > 0 and cats0.isdisjoint(cats1):
                drop2.append(c)
                drop2_reasons[c] = "perfect_categorical_separation"

    drop2 = sorted(set(drop2))
    df3 = df2.drop(columns=drop2, errors="ignore")

    print(f"dataset: {dataset_path}")
    print(f"target:  {target}")
    print(f"rows:    {len(df3)}")
    print(f"dropped(name-based): {len(drop1)}")
    if drop1:
        prev = drop1[:30]
        print(f"  preview: {prev}{' ...' if len(drop1) > 30 else ''}")
    print(f"dropped(value-based): {len(drop2)}")
    if drop2:
        prev = [(c, drop2_reasons.get(c)) for c in drop2[:30]]
        print(f"  preview: {prev}{' ...' if len(drop2) > 30 else ''}")

    if args.audit_only:
        return

    feature_cols = [c for c in df3.columns if c != target]

    num_feats = []
    cat_feats = []
    for c in feature_cols:
        s = df3[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            num_feats.append(c)
        else:
            cat_feats.append(c)

    print(f"features: num={len(num_feats)} cat={len(cat_feats)} total={len(feature_cols)}")

    X = df3[feature_cols]

    pipe = build_pipeline(num_feats=num_feats, cat_feats=cat_feats)

    cv = StratifiedKFold(n_splits=max(2, args.cv), shuffle=True, random_state=42)

    aucs = cross_val_score(pipe, X, y, cv=cv, scoring="roc_auc", error_score="raise")
    accs = cross_val_score(pipe, X, y, cv=cv, scoring="accuracy", error_score="raise")

    print(f"ROC AUC: {aucs.mean():.4f} ± {aucs.std():.4f}")
    print(f"ACC:     {accs.mean():.4f} ± {accs.std():.4f}")

    pipe.fit(X, y)

    if not args.no_save:
        out_path = Path(args.model_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pipeline": pipe,
            "num_feats": num_feats,
            "cat_feats": cat_feats,
            "target": target,
            "dataset": str(dataset_path),
            "dropped_name_based": drop1,
            "dropped_value_based": drop2,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        joblib.dump(payload, out_path)
        print(f"Saved model to: {out_path.resolve()}")


if __name__ == "__main__":
    main()