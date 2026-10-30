"""Save each supplier's matching tenders as a committed snapshot, shown when GeM can't be reached.

    python -m backend.tools.snapshot_matches

Runs the live match search (GeM + TinyFish) per supplier profile and writes backend/corpus/matches_snapshot/<id>.json.
Run it from India (GeM refuses some cloud servers), then commit the files.
"""

import json
import sys

from backend import config  # noqa: F401  (loads .env)
from backend import data, matching


def main():
    matching.SNAPSHOT_DIR.mkdir(exist_ok=True)
    for p in data.fresh_profiles():
        r = matching.find_matches(p, use_cache=False)
        if r["sources"]["gem"].get("error") or r.get("snapshot"):
            print(f"{p['id']}: GeM unreachable, snapshot not updated ({r['sources']['gem'].get('error')})")
            continue
        out = {k: v for k, v in r.items() if k != "cached"}
        (matching.SNAPSHOT_DIR / f"{p['id']}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{p['id']}: {len(r['matches'])} matches saved")


if __name__ == "__main__":
    sys.exit(main())
