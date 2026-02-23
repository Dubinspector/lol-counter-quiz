import numpy as np
import pandas as pd

from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier

df = pd.read_csv(r"out\teams_plus_more.csv")

# odvozené delty z team totals (pokud jsou v CSV)
def delta(col_suffix: str, minute: int):
    a = f"t100_team_m{minute}_{col_suffix}"
    b = f"t200_team_m{minute}_{col_suffix}"
    return df[a] - df[b]

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
    "diff_wardsPlaced10",
    "diff_wardsKilled10",
    "diff_ctrlWardsPlaced10",
    "diff_wardsPlaced15",
    "diff_wardsKilled15",
    "diff_ctrlWardsPlaced15",
]

X = df[base_feats + obj_feats + more_feats].copy()
y = df["team100_win"].astype(int)

mask = ~X.isna().any(axis=1)
X = X[mask]
y = y[mask]
print("usable rows:", len(X), "features:", X.shape[1])

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

logreg = Pipeline([
    ("scaler", StandardScaler()),
    ("clf", LogisticRegression(max_iter=4000, C=1.0)),
])

hgb = HistGradientBoostingClassifier(
    max_depth=3,
    learning_rate=0.08,
    max_iter=400,
    random_state=42
)

def eval_model(name, model):
    auc = cross_val_score(model, X, y, cv=cv, scoring="roc_auc")
    acc = cross_val_score(model, X, y, cv=cv, scoring="accuracy")
    print(f"\n{name}")
    print(f"ROC AUC: {auc.mean():.4f} ± {auc.std():.4f}")
    print(f"ACC:     {acc.mean():.4f} ± {acc.std():.4f}")

eval_model("LogReg", logreg)
eval_model("HistGradientBoosting", hgb)