import os
import json
from pathlib import Path

import pandas as pd
from tqdm import tqdm


MATCH_DIR = Path("match")
TL_DIR = Path("timeline")
OUT_DIR = Path("out")
OUT_DIR.mkdir(exist_ok=True)

# chceme snapshoty z timeline v minutě 10 a 15 (index frame = minute)
SNAP_MINUTES = [10, 15]


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_frame(tl: dict, minute: int):
    frames = tl.get("info", {}).get("frames", [])
    if not frames:
        return None
    # Riot timeline frames jsou po 60s; minute -> index
    idx = minute
    if idx < 0 or idx >= len(frames):
        return None
    return frames[idx]


def extract_participant_snapshot(tl: dict, minute: int, participant_id: int):
    frame = get_frame(tl, minute)
    if frame is None:
        return {}

    pf = frame.get("participantFrames", {})
    key = str(participant_id)
    if key not in pf:
        return {}

    x = pf[key]
    # tyhle fieldy bývají stabilně dostupné
    return {
        f"m{minute}_totalGold": x.get("totalGold"),
        f"m{minute}_xp": x.get("xp"),
        f"m{minute}_level": x.get("level"),
        f"m{minute}_minionsKilled": x.get("minionsKilled"),
        f"m{minute}_jungleMinionsKilled": x.get("jungleMinionsKilled"),
        f"m{minute}_currentGold": x.get("currentGold"),
    }


def extract_team_snapshot(tl: dict, minute: int, team_participant_ids: list[int]):
    frame = get_frame(tl, minute)
    if frame is None:
        return {}

    pf = frame.get("participantFrames", {})
    total_gold = 0
    total_xp = 0
    total_cs = 0
    total_lvl = 0
    ok = 0

    for pid in team_participant_ids:
        key = str(pid)
        if key not in pf:
            continue
        x = pf[key]
        g = x.get("totalGold")
        xp = x.get("xp")
        cs = (x.get("minionsKilled") or 0) + (x.get("jungleMinionsKilled") or 0)
        lvl = x.get("level")
        if g is None or xp is None or lvl is None:
            continue
        total_gold += g
        total_xp += xp
        total_cs += cs
        total_lvl += lvl
        ok += 1

    if ok == 0:
        return {}

    return {
        f"team_m{minute}_totalGold": total_gold,
        f"team_m{minute}_xp": total_xp,
        f"team_m{minute}_cs": total_cs,
        f"team_m{minute}_levelSum": total_lvl,
        f"team_m{minute}_participants_ok": ok,
    }


def main():
    match_files = sorted(MATCH_DIR.glob("*.json"))
    rows = []
    team_rows = []

    for mp in tqdm(match_files, desc="building"):
        match = load_json(mp)

        info = match.get("info", {})
        metadata = match.get("metadata", {})
        match_id = metadata.get("matchId") or mp.stem

        tl_path = TL_DIR / f"{mp.stem}.json"
        if not tl_path.exists():
            # dataset je spárovaný, ale necháme fallback
            continue
        tl = load_json(tl_path)

        # match-level
        base_match = {
            "matchId": match_id,
            "gameCreation": info.get("gameCreation"),
            "gameDuration": info.get("gameDuration"),
            "gameVersion": info.get("gameVersion"),
            "queueId": info.get("queueId"),
            "mapId": info.get("mapId"),
            "platformId": info.get("platformId"),
        }

        participants = info.get("participants", [])
        if len(participants) != 10:
            continue

        # team participantId seznamy (pro týmové agregace)
        team100 = [p.get("participantId") for p in participants if p.get("teamId") == 100]
        team200 = [p.get("participantId") for p in participants if p.get("teamId") == 200]

        # týmové snapshoty + delty
        team_base = dict(base_match)
        for m in SNAP_MINUTES:
            s100 = extract_team_snapshot(tl, m, team100)
            s200 = extract_team_snapshot(tl, m, team200)
            for k, v in s100.items():
                team_base[f"t100_{k}"] = v
            for k, v in s200.items():
                team_base[f"t200_{k}"] = v

            # delta jen pokud máme obě strany
            g100 = s100.get(f"team_m{m}_totalGold")
            g200 = s200.get(f"team_m{m}_totalGold")
            if g100 is not None and g200 is not None:
                team_base[f"delta_m{m}_gold_100_minus_200"] = g100 - g200

            xp100 = s100.get(f"team_m{m}_xp")
            xp200 = s200.get(f"team_m{m}_xp")
            if xp100 is not None and xp200 is not None:
                team_base[f"delta_m{m}_xp_100_minus_200"] = xp100 - xp200

        # win label po týmech (z participants/teams)
        teams = info.get("teams", [])
        win100 = None
        win200 = None
        for t in teams:
            if t.get("teamId") == 100:
                win100 = 1 if t.get("win") else 0
            if t.get("teamId") == 200:
                win200 = 1 if t.get("win") else 0
        team_base["team100_win"] = win100
        team_base["team200_win"] = win200
        team_rows.append(team_base)

        # participant rows
        for p in participants:
            pid = p.get("participantId")
            row = dict(base_match)

            row.update({
                "puuid": p.get("puuid"),
                "riotIdGameName": p.get("riotIdGameName"),
                "riotIdTagline": p.get("riotIdTagline"),
                "teamId": p.get("teamId"),
                "participantId": pid,

                "championId": p.get("championId"),
                "championName": p.get("championName"),
                "teamPosition": p.get("teamPosition"),
                "lane": p.get("lane"),
                "role": p.get("role"),
                "individualPosition": p.get("individualPosition"),

                "summoner1Id": p.get("summoner1Id"),
                "summoner2Id": p.get("summoner2Id"),

                # end-of-game (užitečné na sanity checks; do predikce win to nepoužívej)
                "kills": p.get("kills"),
                "deaths": p.get("deaths"),
                "assists": p.get("assists"),
                "totalDamageDealtToChampions": p.get("totalDamageDealtToChampions"),
                "goldEarned": p.get("goldEarned"),
                "totalMinionsKilled": p.get("totalMinionsKilled"),
                "neutralMinionsKilled": p.get("neutralMinionsKilled"),
                "win": 1 if p.get("win") else 0,
            })

            # timeline snapshoty
            for m in SNAP_MINUTES:
                row.update(extract_participant_snapshot(tl, m, pid))

            rows.append(row)

    dfp = pd.DataFrame(rows)
    dft = pd.DataFrame(team_rows)

    out_p = OUT_DIR / "participants.csv"
    out_t = OUT_DIR / "teams.csv"
    dfp.to_csv(out_p, index=False, encoding="utf-8")
    dft.to_csv(out_t, index=False, encoding="utf-8")

    print(f"written: {out_p} rows={len(dfp)} cols={len(dfp.columns)}")
    print(f"written: {out_t} rows={len(dft)} cols={len(dft.columns)}")


if __name__ == "__main__":
    main()