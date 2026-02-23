import json
from pathlib import Path
import pandas as pd

MATCH_DIR = Path(r"match")
TL_DIR    = Path(r"timeline")
OUT_OBJ   = Path(r"out\objectives.csv")
OUT_MERGE = Path(r"out\teams_plus.csv")

CUT10 = 10 * 60 * 1000
CUT14 = 14 * 60 * 1000
CUT15 = 15 * 60 * 1000

def load_json(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def get_participant_team_map(match_json: dict):
    # participantId -> teamId (100/200)
    m = {}
    for p in match_json.get("info", {}).get("participants", []):
        pid = p.get("participantId")
        tid = p.get("teamId")
        if pid is not None and tid is not None:
            m[int(pid)] = int(tid)
    return m

def team_from_pid(pid, pid2team):
    if pid is None:
        return None
    try:
        pid = int(pid)
    except Exception:
        return None
    return pid2team.get(pid)

def update_counts(counts, team, field, inc=1):
    if team not in (100, 200):
        return
    counts[team][field] += inc

def compute_features(match_id: str, match_json: dict, tl_json: dict):
    pid2team = get_participant_team_map(match_json)

    # per team counters
    base = {
        100: dict(k10=0, d10=0, a10=0, k15=0, d15=0, a15=0, plates14=0, towers15=0, drakes15=0, herald15=0),
        200: dict(k10=0, d10=0, a10=0, k15=0, d15=0, a15=0, plates14=0, towers15=0, drakes15=0, herald15=0),
    }

    first_blood_team = 0
    first_drake_team = 0
    first_tower_team = 0
    first_herald_team = 0

    frames = tl_json.get("info", {}).get("frames", [])
    for fr in frames:
        events = fr.get("events", [])
        for ev in events:
            ts = ev.get("timestamp")
            if ts is None:
                continue
            if ts > CUT15:
                continue

            et = ev.get("type")

            # Champion kill
            if et == "CHAMPION_KILL":
                killer_team = team_from_pid(ev.get("killerId"), pid2team)
                victim_team = team_from_pid(ev.get("victimId"), pid2team)
                assists = ev.get("assistingParticipantIds") or []

                if first_blood_team == 0 and killer_team in (100, 200):
                    first_blood_team = killer_team

                if ts <= CUT10:
                    update_counts(base, killer_team, "k10", 1)
                    update_counts(base, victim_team, "d10", 1)
                    for ap in assists:
                        update_counts(base, team_from_pid(ap, pid2team), "a10", 1)

                # 15 includes 10 automatically, but tady počítáme přímo do 15
                update_counts(base, killer_team, "k15", 1)
                update_counts(base, victim_team, "d15", 1)
                for ap in assists:
                    update_counts(base, team_from_pid(ap, pid2team), "a15", 1)

            # Turret plates (do 14:00)
            elif et == "TURRET_PLATE_DESTROYED":
                if ts <= CUT14:
                    killer_team = team_from_pid(ev.get("killerId"), pid2team)
                    update_counts(base, killer_team, "plates14", 1)

            # Buildings (towers)
            elif et == "BUILDING_KILL":
                btype = ev.get("buildingType")
                if btype == "TOWER_BUILDING":
                    killer_team = team_from_pid(ev.get("killerId"), pid2team)
                    # fallback: některé eventy mají killerTeamId
                    if killer_team not in (100, 200):
                        kt = ev.get("killerTeamId")
                        if kt in (100, 200):
                            killer_team = kt

                    if first_tower_team == 0 and killer_team in (100, 200):
                        first_tower_team = killer_team

                    update_counts(base, killer_team, "towers15", 1)

            # Elite monsters (drake / herald)
            elif et == "ELITE_MONSTER_KILL":
                mtype = ev.get("monsterType")
                killer_team = team_from_pid(ev.get("killerId"), pid2team)
                if killer_team not in (100, 200):
                    kt = ev.get("killerTeamId")
                    if kt in (100, 200):
                        killer_team = kt

                if mtype == "DRAGON":
                    if first_drake_team == 0 and killer_team in (100, 200):
                        first_drake_team = killer_team
                    update_counts(base, killer_team, "drakes15", 1)

                elif mtype == "RIFTHERALD":
                    if first_herald_team == 0 and killer_team in (100, 200):
                        first_herald_team = killer_team
                    update_counts(base, killer_team, "herald15", 1)

    # diffs (t100 - t200)
    def diff(field):
        return base[100][field] - base[200][field]

    # first objective encoded: 1 (team100), -1 (team200), 0 (none)
    def first_enc(team):
        if team == 100:
            return 1
        if team == 200:
            return -1
        return 0

    row = {
        "match_id": match_id,

        "diff_k10": diff("k10"),
        "diff_d10": diff("d10"),
        "diff_a10": diff("a10"),
        "diff_k15": diff("k15"),
        "diff_d15": diff("d15"),
        "diff_a15": diff("a15"),

        "diff_plates14": diff("plates14"),
        "diff_towers15": diff("towers15"),
        "diff_drakes15": diff("drakes15"),
        "diff_herald15": diff("herald15"),

        "first_blood": first_enc(first_blood_team),
        "first_drake": first_enc(first_drake_team),
        "first_tower": first_enc(first_tower_team),
        "first_herald": first_enc(first_herald_team),
    }
    return row

def main():
    rows = []

    tl_files = sorted(TL_DIR.glob("*.json"))
    for tl_path in tl_files:
        match_id = tl_path.stem  # EUW1_...
        m_path = MATCH_DIR / f"{match_id}.json"
        if not m_path.exists():
            continue

        match_json = load_json(m_path)
        tl_json = load_json(tl_path)

        rows.append(compute_features(match_id, match_json, tl_json))

    obj = pd.DataFrame(rows).sort_values("match_id")
    obj.to_csv(OUT_OBJ, index=False)
    print(f"written: {OUT_OBJ} rows={len(obj)} cols={len(obj.columns)}")

    teams = pd.read_csv(r"out\teams.csv")

    # najdi match id sloupec v teams.csv
    key_col = None
    for c in teams.columns:
        cl = c.lower()
        if cl in {"match_id", "matchid"}:
            key_col = c
            break
    if key_col is None:
        raise SystemExit("teams.csv: chybí sloupec match_id/matchId")

    merged = teams.merge(obj, left_on=key_col, right_on="match_id", how="left")
    merged.to_csv(OUT_MERGE, index=False)
    print(f"written: {OUT_MERGE} rows={len(merged)} cols={len(merged.columns)}")

if __name__ == "__main__":
    main()