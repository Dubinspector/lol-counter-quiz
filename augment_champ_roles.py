import json
from pathlib import Path
import pandas as pd

MATCH_DIR = Path(r"match")
OUT_CH = Path(r"out\champ_roles.csv")
OUT_FULL = Path(r"out\teams_full.csv")

ROLES = ["TOP","JUNGLE","MIDDLE","BOTTOM","UTILITY"]

def load_json(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def main():
    rows = []
    for m_path in sorted(MATCH_DIR.glob("*.json")):
        match_id = m_path.stem
        mj = load_json(m_path)
        parts = mj.get("info", {}).get("participants", [])

        row = {"match_id": match_id}
        # init
        for tid in (100, 200):
            for r in ROLES:
                row[f"t{tid}_{r}_champ"] = None

        for p in parts:
            tid = p.get("teamId")
            role = p.get("teamPosition")  # TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY
            champ = p.get("championId")
            if tid in (100, 200) and role in ROLES and champ is not None:
                key = f"t{tid}_{role}_champ"
                if row[key] is None:  # první výskyt ber
                    row[key] = int(champ)

        rows.append(row)

    ch = pd.DataFrame(rows).sort_values("match_id")
    ch.to_csv(OUT_CH, index=False)
    print(f"written: {OUT_CH} rows={len(ch)} cols={len(ch.columns)}")

    base = pd.read_csv(r"out\teams_plus_more.csv")
    key = None
    for c in base.columns:
        if c.lower() in {"match_id", "matchid"}:
            key = c
            break
    if key is None:
        raise SystemExit("teams_plus_more.csv: chybí sloupec match_id/matchId")

    full = base.merge(ch, left_on=key, right_on="match_id", how="left")
    full.to_csv(OUT_FULL, index=False)
    print(f"written: {OUT_FULL} rows={len(full)} cols={len(full.columns)}")

if __name__ == "__main__":
    main()