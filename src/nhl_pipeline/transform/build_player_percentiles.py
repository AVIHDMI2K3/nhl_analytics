"""Phase 7: build the skater percentile table (for the pizza charts) for one season.

Run from the repo root with the `nhl` conda environment active, after build_season_display.py and
build_player_advanced.py:

    python src/nhl_pipeline/transform/build_player_percentiles.py --season 2025
    python src/nhl_pipeline/transform/build_player_percentiles.py --season 2025 --min-minutes 500

Reads  data/metrics/season=2025/player_season_display.parquet, player_season_advanced.parquet
Writes data/metrics/season=2025/player_season_percentiles.parquet   one row per skater and stat

See percentiles.py for the pools and the percentile rule. Forwards are ranked against forwards and defensemen against
defensemen, each season on its own, among players with at least --min-minutes of 5v5 time (default 600).
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from percentiles import DEFAULT_CHART, GROUPS, STATS_BY_KEY, build_percentile_rows

REPO_ROOT = Path(__file__).resolve().parents[3]
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
DEFAULT_MIN_MINUTES = 600
SCHEMA = pa.schema([
    ("season", pa.int64()), ("player_id", pa.int64()), ("name", pa.string()), ("position", pa.string()),
    ("position_group", pa.string()), ("team", pa.string()), ("teams", pa.string()), ("minutes_5v5", pa.float64()),
    ("in_pool", pa.bool_()), ("stat", pa.string()), ("label", pa.string()), ("value", pa.float64()),
    ("percentile", pa.float64()), ("pool_size", pa.int64()), ("higher_is_better", pa.bool_()),
    ("in_default_chart", pa.bool_()),
])
SAMPLE_PLAYERS = ("McDavid", "Makar", "Matthews", "Hedman", "Hughes")


def main():
    parser = argparse.ArgumentParser(description="Build the skater percentile table for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--min-minutes", type=float, default=DEFAULT_MIN_MINUTES)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    metrics = args.metrics_root / f"season={args.season}"
    display = pq.read_table(metrics / "player_season_display.parquet").to_pylist()
    advanced = pq.read_table(metrics / "player_season_advanced.parquet").to_pylist()
    rows = build_percentile_rows(args.season, display, advanced, min_minutes=args.min_minutes)
    out = metrics / "player_season_percentiles.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), out, compression="zstd")

    players = {(r["player_id"]): r for r in rows}
    print(f"season {args.season}: {len(players)} skaters, {len(rows)} rows -> {out}")
    for group in GROUPS:
        members = [r for r in players.values() if r["position_group"] == group]
        pool = sum(1 for r in members if r["in_pool"])
        print(f"  {group}: {len(members)} skaters, {pool} in the pool (at least {args.min_minutes:g} min of 5v5)")

    for r in sorted((r for r in players.values() if any(s in r["name"] for s in SAMPLE_PLAYERS) and r["in_pool"]),
                    key=lambda r: r["name"]):
        chart = [x for x in rows if x["player_id"] == r["player_id"] and x["in_default_chart"]]
        print(f"\n  {r['name']} ({r['team']}, {r['position']}, {r['minutes_5v5']:.0f} min)")
        for key in DEFAULT_CHART[r["position_group"]]:
            x = next(c for c in chart if c["stat"] == key)
            shown = "-" if x["value"] is None else f"{x['value']:.2f}"
            pct = "-" if x["percentile"] is None else f"{x['percentile']:.0f}"
            print(f"    {STATS_BY_KEY[key][1]:<48} {shown:>8}   percentile {pct:>3}")


if __name__ == "__main__":
    main()