import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score

df = pd.read_csv(r"out\teams_plus.csv")

# odvozené delty z totals
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
    "d10_cs",
    "d15_cs",
    "d10_lvl",
    "d15_lvl",
]

obj_feats = [
    "diff_k10","diff_d10","diff_a10",
    "diff_k15","diff_d15","diff_a15",
    "diff_plates14","diff_towers15","diff_drakes15","diff_herald15",
    "first_blood","first_drake","first_tower","first_herald",
]

X = df[base_feats + obj_feats].copy()
y = df["team100_win"].astype(int)

mask = ~X.isna().any(axis=1)
X = X[mask]
y = y[mask]
print("usable rows:", len(X))

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

model = Pipeline([
    ("scaler", StandardScaler()),
    ("clf", LogisticRegression(max_iter=3000)),
])

model.fit(X_train, y_train)
proba = model.predict_proba(X_test)[:, 1]
pred = (proba >= 0.5).astype(int)

print("Accuracy:", accuracy_score(y_test, pred))
print("ROC AUC:", roc_auc_score(y_test, proba))