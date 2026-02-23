import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score, confusion_matrix, classification_report

df = pd.read_csv(r"out\teams.csv")

# odvozené delty z team totals (už jsou v souboru)
def delta(col_suffix: str, minute: int):
    a = f"t100_team_m{minute}_{col_suffix}"
    b = f"t200_team_m{minute}_{col_suffix}"
    return df[a] - df[b]

df["d10_cs"] = delta("cs", 10)
df["d15_cs"] = delta("cs", 15)
df["d10_lvl"] = delta("levelSum", 10)
df["d15_lvl"] = delta("levelSum", 15)

X = df[
    [
        "delta_m10_gold_100_minus_200",
        "delta_m10_xp_100_minus_200",
        "delta_m15_gold_100_minus_200",
        "delta_m15_xp_100_minus_200",
        "d10_cs",
        "d15_cs",
        "d10_lvl",
        "d15_lvl",
    ]
].copy()

y = df["team100_win"].astype(int)

mask = ~X.isna().any(axis=1)
X = X[mask]
y = y[mask]

print("usable rows (no NaN):", len(X))

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

model = Pipeline(
    steps=[
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000)),
    ]
)

model.fit(X_train, y_train)

proba = model.predict_proba(X_test)[:, 1]
pred = (proba >= 0.5).astype(int)

acc = accuracy_score(y_test, pred)
auc = roc_auc_score(y_test, proba)

print("\nAccuracy:", acc)
print("ROC AUC:", auc)
print("\nConfusion matrix:\n", confusion_matrix(y_test, pred))
print("\nReport:\n", classification_report(y_test, pred, digits=4))

# koeficienty (po standardizaci)
clf = model.named_steps["clf"]
cols = X.columns.tolist()
coef = pd.Series(clf.coef_[0], index=cols).sort_values(key=lambda s: s.abs(), ascending=False)
print("\nTop coefficients (abs):")
print(coef)