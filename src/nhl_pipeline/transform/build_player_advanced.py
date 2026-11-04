"""Phase 4.7: build the advanced on-ice skater table for one season.

Run from the repo root with the `nhl` conda environment active, after build_base_tables.py
and build_season_totals.py:

    python src/nhl_pipeline/transform/build_player_advanced.py --season 2025

Reads  data/metrics/season=2025/{player_game_strength,team_game_strength,player_season_totals}.parquet
       data/staging/season=2025/{games,players}.parquet
Writes data/metrics/season=2025/player_season_advanced.parquet

See advanced_stats.py for what a row holds. Covers only games with shift data.
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from advanced_stats import COUNT_COLUMNS, RATE_COLUMNS, build_advanced_counts, build_advanced_display
from build_season_display import full_names, team_abbrevs

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
SCHEMA = pa.schema(
    [("season", pa.int64()), ("player_id", pa.int64()), ("name", pa.string()), ("position", pa.string()),
     ("kind", pa.string()), ("team_id", pa.int64()), ("team", pa.string()), ("teams", pa.string()),
     ("situation", pa.string()), ("games_played", pa.int64()), ("games_included", pa.int64())]
    + [(column, pa.int64()) for column in COUNT_COLUMNS]
    + [(column, pa.float64()) for column in RATE_COLUMNS]
)


def write_table(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, compression="zstd")


def main():
    parser = argparse.ArgumentParser(description="Build the advanced on-ice skater table.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    metrics = args.metrics_root / f"season={args.season}"
    staging = args.staging_root / f"season={args.season}"
    player_rows = pq.read_table(metrics / "player_game_strength.parquet").to_pylist()
    team_rows = pq.read_table(metrics / "team_game_strength.parquet").to_pylist()
    season_rows = pq.read_table(metrics / "player_season_totals.parquet").to_pylist()

    totals, games = build_advanced_counts(player_rows, team_rows)
    rows = build_advanced_display(totals, games, season_rows, full_names(staging), team_abbrevs(staging))
    for row in rows:
        row["season"] = args.season
    out = metrics / "player_season_advanced.parquet"
    write_table(out, rows)

    by_situation = {}
    for row in rows:
        by_situation[row["situation"]] = by_situation.get(row["situation"], 0) + 1
    print(f"Season {args.season}: {len(rows)} rows; by situation: " + ", ".join(f"{k} {v}" for k, v in by_situation.items()))
    print(f"Written to {out}")
    shown = [
        r for r in rows
        if r["situation"] == "5v5" and (r["kind"] == "total" or r["teams"] == r["team"]) and r["seconds"] >= 600 * 60
    ]
    print("\n5v5 leaders by Corsi % (at least 600 minutes at 5v5):")
    for r in sorted(shown, key=lambda r: -r["cf_pct"])[:8]:
        print(f"  {r['name']:24s} {r['team']:4s} GP {r['games_played']:3d}/{r['games_included']:3d}  TOI {r['seconds'] / 60:7.1f}  "
              f"CF {r['cf']:5d} CA {r['ca']:5d}  CF% {r['cf_pct']:5.1f}  CF% rel {r['cf_pct_rel']:+5.1f}")


if __name__ == "__main__":
    main()