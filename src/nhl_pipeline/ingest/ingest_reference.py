"""Download the NHL's own season time-on-ice totals. They are used only to check our numbers.

Run from the repo root with the `nhl` conda environment active:

    python src/nhl_pipeline/ingest/ingest_reference.py --season 2023

Saves data/raw/season=2023/reference/skater_timeonice.json.gz, the response exactly as
received: one row per skater for the regular season, with total, even-strength,
power-play and shorthanded time on ice in seconds, shifts and games played.
"""

import argparse
import json
import sys
from pathlib import Path

from endpoints import STATS_BASE, Fetcher
from rawstore import reference_path, write_gz_atomic

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_ROOT = REPO_ROOT / "data" / "raw"


def main():
    parser = argparse.ArgumentParser(description="Download the NHL's season time-on-ice totals.")
    parser.add_argument("--season", type=int, required=True, help="start year, 2023 = 2023-24")
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--min-interval", type=float, default=1.0)
    args = parser.parse_args()

    season_id = f"{args.season}{args.season + 1}"
    response = Fetcher(min_interval=args.min_interval).get(
        f"{STATS_BASE}/skater/timeonice",
        params={
            "isAggregate": "false",
            "isGame": "false",
            "limit": -1,
            "start": 0,
            "cayenneExp": f"seasonId={season_id} and gameTypeId=2",
        },
    )
    if response.status_code != 200:
        sys.exit(f"The NHL answered {response.status_code}; nothing was saved.")
    body = json.loads(response.content)
    rows, total = len(body["data"]), body["total"]
    if rows != total:
        sys.exit(f"Got {rows} rows but the NHL reports {total}; nothing was saved.")

    path = reference_path(args.raw_root, args.season, "skater_timeonice")
    write_gz_atomic(path, response.content)
    print(f"Saved {rows} skaters to {path}")


if __name__ == "__main__":
    main()