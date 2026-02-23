import pandas as pd

df = pd.read_csv(r"out\teams.csv")

features = [
    "delta_m10_gold_100_minus_200",
    "delta_m10_xp_100_minus_200",
    "delta_m15_gold_100_minus_200",
    "delta_m15_xp_100_minus_200",
]

print("rows:", len(df))
print("\nNaN per feature:")
print(df[features].isna().sum())

bad = df[features].isna().any(axis=1).sum()
print("\nrows with any NaN in selected features:", bad)

print("\nmin/max deltas:")
for c in features:
    s = df[c].dropna()
    print(f"{c}: min={s.min()} max={s.max()}")