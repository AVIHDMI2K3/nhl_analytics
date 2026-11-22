"""Phase 6: build the zone starts (faceoffs) of lines and defense pairs at 5v5 for one season.

Run from the repo root with the `nhl` conda environment active, after build_stints.py:

    python src/nhl_pipeline/transform/build_unit_zone_starts.py --season 2025

Reads  data/staging/season=2025/{games,boxscore_players,events}.parquet, data/metrics/season=2025/stints.parquet
Writes data/metrics/season=2025/unit_zone_starts_5v5.parquet   one row per team and unit: oz, dz, nz, oz_start_pct

See zone_starts.py for the rules. It prints how many faceoff sides at 5v5 were counted and how many of them a line and
a pair were found for, and the league total of oz and dz (each offensive-zone faceoff is one team's oz and the other's
dz, so with every unit found they would be equal).
"""

import argparse
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from line_tables import positions_by_game
from zone_starts import season_zone_rows, unit_zone_starts

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
EVENT_COLUMNS = ["game_id", "event_type", "event_owner_team_id", "zone_code", "situation_code", "game_seconds"]
SCHEMA = pa.schema(
    [
        ("season", pa.int64()),
        ("team_id", pa.int64()),
        ("unit_type", pa.string()),
        ("player_ids", pa.list_(pa.int64())),
        ("oz", pa.int64()),
        ("dz", pa.int64()),
        ("nz", pa.int64()),
        ("oz_start_pct", pa.float64()),
    ]
)


def group_by_game(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["game_id"]].append(row)
    return groups


def main():
    parser = argparse.ArgumentParser(description="Build the line and pair zone starts for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    staging = args.staging_root / f"season={args.season}"
    metrics = args.metrics_root / f"season={args.season}"
    games = {
        g["game_id"]: g
        for g in pq.read_table(
            staging / "games.parquet", columns=["game_id", "home_team_id", "away_team_id"]
        ).to_pylist()
    }
    positions = positions_by_game(
        pq.read_table(
            staging / "boxscore_players.parquet", columns=["game_id", "player_id", "position", "player_group"]
        ).to_pylist()
    )
    stints = group_by_game(pq.read_table(metrics / "stints.parquet").to_pylist())
    events = group_by_game(
        e
        for e in pq.read_table(staging / "events.parquet", columns=EVENT_COLUMNS).to_pylist()
        if e["event_type"] == "faceoff"
    )

    results, sides = [], 0
    for game_id in sorted(stints):
        totals, counted = unit_zone_starts(
            games[game_id], stints[game_id], events.get(game_id, []), positions.get(game_id, {})
        )
        results.append(totals)
        sides += counted
    rows = season_zone_rows(results)
    for row in rows:
        row["season"] = args.season
    out = metrics / "unit_zone_starts_5v5.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), out, compression="zstd")

    print(f"season {args.season}: {len(rows)} units with a faceoff -> {out}")
    print(f"5v5 faceoff sides counted: {sides}")
    for unit_type in ("line", "pair"):
        subset = [r for r in rows if r["unit_type"] == unit_type]
        found = sum(r["oz"] + r["dz"] + r["nz"] for r in subset)
        oz, dz = sum(r["oz"] for r in subset), sum(r["dz"] for r in subset)
        print(
            f"  {unit_type}: a unit was found for {found} faceoff sides ({100 * found / (sides * 1 or 1):.1f}%); "
            f"league oz {oz}, dz {dz}"
        )


if __name__ == "__main__":
    main()
