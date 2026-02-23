import pandas as pd
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

df = pd.read_csv(r"out\teams_plus_more.csv")

def delta(col_suffix: str, minute: int):
    return df[f"t100_team_m{minute}_{col_suffix}"] - df[f"t200_team_m{minute}_{col_suffix}"]

df["d10_cs"]  = delta("cs", 10)
df["d15_cs"]  = delta("cs", 15)
df["d10_lvl"] = delta("levelSum", 10)
df["d15_lvl"] = delta("levelSum", 15)

base_feats = [
    "delta_m10_gold_100_minus_200",
    "delta_m10_xp_100_minus_200",
    "delta_m15_gold_100_minus_200",
    "delta_m15_xp_100_minus_200",
    "d10_cs","d15_cs","d10_lvl","d15_lvl",
]

obj_feats = [
    "diff_k10","diff_d10","diff_a10",
    "diff_k15","diff_d15","diff_a15",
    "diff_plates14","diff_towers15","diff_drakes15","diff_herald15",
    "first_blood","first_drake","first_tower","first_herald",
]

more_feats = [
    "delta_m8_gold_100_minus_200",
    "delta_m8_xp_100_minus_200",
    "delta_m8_cs_100_minus_200",
    "delta_m8_lvl_100_minus_200",
    "delta_m12_gold_100_minus_200",
    "delta_m12_xp_100_minus_200",
    "delta_m12_cs_100_minus_200",
    "delta_m12_lvl_100_minus_200",
    "diff_wardsPlaced10","diff_wardsKilled10","diff_ctrlWardsPlaced10",
    "diff_wardsPlaced15","diff_wardsKilled15","diff_ctrlWardsPlaced15",
]

y = df["team100_win"].astype(int)

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
model = Pipeline([
    ("scaler", StandardScaler()),
    ("clf", LogisticRegression(max_iter=5000, C=1.0))
])

def run(name, feats):
    X = df[feats].copy()
    mask = ~X.isna().any(axis=1)
    X = X[mask]
    yy = y[mask]
    auc = cross_val_score(model, X, yy, cv=cv, scoring="roc_auc")
    acc = cross_val_score(model, X, yy, cv=cv, scoring="accuracy")
    print(f"\n{name}  rows={len(X)} feats={len(feats)}")
    print(f"ROC AUC: {auc.mean():.4f} ± {auc.std():.4f}")
    print(f"ACC:     {acc.mean():.4f} ± {acc.std():.4f}")

run("BASE", base_feats)
run("BASE+OBJ", base_feats + obj_feats)
run("BASE+OBJ+MORE", base_feats + obj_feats + more_feats)
run("OBJ only", obj_feats)
run("MORE only", more_feats)