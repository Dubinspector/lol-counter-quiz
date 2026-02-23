import numpy as np
import pandas as pd

from sklearn.model_selection import StratifiedKFold, GridSearchCV
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

feats = [
    "delta_m10_gold_100_minus_200","delta_m10_xp_100_minus_200",
    "delta_m15_gold_100_minus_200","delta_m15_xp_100_minus_200",
    "d10_cs","d15_cs","d10_lvl","d15_lvl",
    "diff_k10","diff_d10","diff_a10","diff_k15","diff_d15","diff_a15",
    "diff_plates14","diff_towers15","diff_drakes15","diff_herald15",
    "first_blood","first_drake","first_tower","first_herald",
    "delta_m8_gold_100_minus_200","delta_m8_xp_100_minus_200","delta_m8_cs_100_minus_200","delta_m8_lvl_100_minus_200",
    "delta_m12_gold_100_minus_200","delta_m12_xp_100_minus_200","delta_m12_cs_100_minus_200","delta_m12_lvl_100_minus_200",
    "diff_wardsPlaced10","diff_wardsKilled10","diff_ctrlWardsPlaced10",
    "diff_wardsPlaced15","diff_wardsKilled15","diff_ctrlWardsPlaced15",
]

X = df[feats].copy()
y = df["team100_win"].astype(int)
mask = ~X.isna().any(axis=1)
X = X[mask]
y = y[mask]

pipe = Pipeline([
    ("scaler", StandardScaler()),
    ("clf", LogisticRegression(max_iter=8000, solver="saga"))
])

param_grid = {
    "clf__penalty": ["l2", "l1", "elasticnet"],
    "clf__C": [0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
    "clf__l1_ratio": [0.2, 0.5, 0.8],  # jen pro elasticnet, ostatní ignoruje
}

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
gs = GridSearchCV(pipe, param_grid=param_grid, scoring="roc_auc", cv=cv, n_jobs=-1, refit=True)
gs.fit(X, y)

print("best AUC:", gs.best_score_)
print("best params:", gs.best_params_)