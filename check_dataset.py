# check_dataset.py
from pathlib import Path
import json

MATCH_DIR = Path("match")
TL_DIR = Path("timeline")

def ids_in(dirpath: Path):
    out = set()
    for p in dirpath.glob("*.json"):
        out.add(p.stem)  # EUW1_123...
    return out

match_ids = ids_in(MATCH_DIR)
tl_ids = ids_in(TL_DIR)

only_match = sorted(match_ids - tl_ids)
only_tl = sorted(tl_ids - match_ids)
both = sorted(match_ids & tl_ids)

print(f"match files:    {len(match_ids)}")
print(f"timeline files: {len(tl_ids)}")
print(f"paired:         {len(both)}")
print(f"missing timeline for match: {len(only_match)}")
print(f"missing match for timeline: {len(only_tl)}")

if only_match[:10]:
    print("\nexamples missing timeline:")
    print("\n".join(only_match[:10]))

if only_tl[:10]:
    print("\nexamples missing match:")
    print("\n".join(only_tl[:10]))

# quick JSON sanity sample
sample = both[:5]
for mid in sample:
    m = MATCH_DIR / f"{mid}.json"
    t = TL_DIR / f"{mid}.json"
    try:
        json.loads(m.read_text(encoding="utf-8"))
        json.loads(t.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"\nJSON parse problem for {mid}: {e}")