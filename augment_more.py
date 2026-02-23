import json
from pathlib import Path
import pandas as pd

MATCH_DIR = Path(r"match")
TL_DIR    = Path(r"timeline")

OUT_MORE  = Path(r"out\more.csv")
OUT_MERGE = Path(r"out\teams_plus_more.csv")

CUT8  = 8  * 60 * 1000
CUT10 = 10 * 60 * 1000
CUT12 = 12 * 60 * 1000
CUT15 = 15 * 60 * 1000

def load_json(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def get_pid2team(match_json: dict):
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

def pick_frame(frames, cut_ms: int):
    # vezmi poslední frame s timestamp <= cut; fallback první
    best = None
    for fr in frames:
        ts = fr.get("timestamp")
        if ts is None:
            continue
        if ts <= cut_ms:
            best = fr
        else:
            break
    return best if best is not None else (frames[0] if frames else None)

def sum_team_from_frame(frame, pid2team):
    # vrátí team totals: gold/xp/cs/lvl
    totals = {
        100: dict(gold=0, xp=0, cs=0, lvl=0),
        200: dict(gold=0, xp=0, cs=0, lvl=0),
    }
    pf = frame.get("participantFrames", {}) if frame else {}
    for pid_str, obj in pf.items():
        try:
            pid = int(pid_str)
        except Exception:
            continue
        tid = pid2team.get(pid)
        if tid not in (100, 200):
            continue

        gold = obj.get("totalGold", 0) or 0
        xp   = obj.get("xp", 0) or 0
        lvl  = obj.get("level", 0) or 0
        cs   = (obj.get("minionsKilled", 0) or 0) + (obj.get("jungleMinionsKilled", 0) or 0)

        totals[tid]["gold"] += int(gold)
        totals[tid]["xp"]   += int(xp)
        totals[tid]["cs"]   += int(cs)
        totals[tid]["lvl"]  += int(lvl)

    return totals

def count_wards(frames, pid2team):
    # diffs do 10/15 min: wards placed/killed + control wards placed
    c = {
        100: dict(wp10=0, wk10=0, cwp10=0, wp15=0, wk15=0, cwp15=0),
        200: dict(wp10=0, wk10=0, cwp10=0, wp15=0, wk15=0, cwp15=0),
    }

    for fr in frames:
        events = fr.get("events", [])
        for ev in events:
            ts = ev.get("timestamp")
            if ts is None or ts > CUT15:
                continue

            et = ev.get("type")
            if et == "WARD_PLACED":
                tid = team_from_pid(ev.get("creatorId"), pid2team)
                if tid not in (100, 200):
                    continue
                ward_type = ev.get("wardType") or ""
                if ts <= CUT10:
                    c[tid]["wp10"] += 1
                    if ward_type == "CONTROL_WARD":
                        c[tid]["cwp10"] += 1
                c[tid]["wp15"] += 1
                if ward_type == "CONTROL_WARD":
                    c[tid]["cwp15"] += 1

            elif et == "WARD_KILL":
                tid = team_from_pid(ev.get("killerId"), pid2team)
                if tid not in (100, 200):
                    continue
                if ts <= CUT10:
                    c[tid]["wk10"] += 1
                c[tid]["wk15"] += 1

    def diff(field):
        return c[100][field] - c[200][field]

    return {
        "diff_wardsPlaced10": diff("wp10"),
        "diff_wardsKilled10": diff("wk10"),
        "diff_ctrlWardsPlaced10": diff("cwp10"),
        "diff_wardsPlaced15": diff("wp15"),
        "diff_wardsKilled15": diff("wk15"),
        "diff_ctrlWardsPlaced15": diff("cwp15"),
    }

def main():
    rows = []

    for tl_path in sorted(TL_DIR.glob("*.json")):
        match_id = tl_path.stem
        m_path = MATCH_DIR / f"{match_id}.json"
        if not m_path.exists():
            continue

        match_json = load_json(m_path)
        tl_json = load_json(tl_path)

        pid2team = get_pid2team(match_json)
        frames = tl_json.get("info", {}).get("frames", [])

        fr8  = pick_frame(frames, CUT8)
        fr12 = pick_frame(frames, CUT12)

        t8  = sum_team_from_frame(fr8, pid2team)
        t12 = sum_team_from_frame(fr12, pid2team)

        def d(tot, field):
            return tot[100][field] - tot[200][field]

        ward_feats = count_wards(frames, pid2team)

        row = {
            "match_id": match_id,

            "delta_m8_gold_100_minus_200":  d(t8,  "gold"),
            "delta_m8_xp_100_minus_200":    d(t8,  "xp"),
            "delta_m8_cs_100_minus_200":    d(t8,  "cs"),
            "delta_m8_lvl_100_minus_200":   d(t8,  "lvl"),

            "delta_m12_gold_100_minus_200": d(t12, "gold"),
            "delta_m12_xp_100_minus_200":   d(t12, "xp"),
            "delta_m12_cs_100_minus_200":   d(t12, "cs"),
            "delta_m12_lvl_100_minus_200":  d(t12, "lvl"),
        }
        row.update(ward_feats)
        rows.append(row)

    more = pd.DataFrame(rows).sort_values("match_id")
    more.to_csv(OUT_MORE, index=False)
    print(f"written: {OUT_MORE} rows={len(more)} cols={len(more.columns)}")

    base = pd.read_csv(r"out\teams_plus.csv")

    key_col = None
    for c in base.columns:
        if c.lower() in {"match_id", "matchid"}:
            key_col = c
            break
    if key_col is None:
        raise SystemExit("teams_plus.csv: chybí sloupec match_id/matchId")

    merged = base.merge(more, left_on=key_col, right_on="match_id", how="left")
    merged.to_csv(OUT_MERGE, index=False)
    print(f"written: {OUT_MERGE} rows={len(merged)} cols={len(merged.columns)}")

if __name__ == "__main__":
    main()