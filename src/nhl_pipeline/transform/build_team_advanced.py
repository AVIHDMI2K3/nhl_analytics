"""Phase 4.8: build the advanced on-ice team table for one season.

Run from the repo root with the `nhl` conda environment active, after build_base_tables.py:

    python src/nhl_pipeline/transform/build_team_advanced.py --season 2025

Reads  data/metrics/season=2025/team_game_strength.parquet
       data/staging/season=2025/games.parquet
Writes data/metrics/season=2025/team_season_advanced.parquet

One row per team and situation (all, ev, 5v5, pp, sh); see advanced_stats.py. Counts cover only
games with shift data. games_played is every regular-season game the team played.
"""

import argparse
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from advanced_stats import ON_ICE, TEAM_RATE_COLUMNS, build_team_advanced_counts, build_team_advanced_display
from build_season_display import team_abbrevs

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
REGULAR_SEASON = 2
SCHEMA = pa.schema(
    [
        ("season", pa.int64()),
        ("team_id", pa.int64()),
        ("team", pa.string()),
        ("situation", pa.string()),
        ("games_played", pa.int64()),
        ("games_included", pa.int64()),
    ]
    + [(column, pa.int64()) for column in ON_ICE]
    + [(column, pa.float64()) for column in TEAM_RATE_COLUMNS]
)


def write_table(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, compression="zstd")


def games_by_team(staging):
    played = Counter()
    for game in pq.read_table(
        staging / "games.parquet", columns=["game_type", "has_boxscore", "home_team_id", "away_team_id"]
    ).to_pylist():
        if game["game_type"] == REGULAR_SEASON and game["has_boxscore"]:
            played[game["home_team_id"]] += 1
            played[game["away_team_id"]] += 1
    return dict(played)


def main():
    parser = argparse.ArgumentParser(description="Build the advanced on-ice team table.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    metrics = args.metrics_root / f"season={args.season}"
    staging = args.staging_root / f"season={args.season}"
    team_rows = pq.read_table(metrics / "team_game_strength.parquet").to_pylist()
    totals, games = build_team_advanced_counts(team_rows)
    rows = build_team_advanced_display(totals, games, games_by_team(staging), team_abbrevs(staging))
    for row in rows:
        row["season"] = args.season
    out = metrics / "team_season_advanced.parquet"
    write_table(out, rows)

    print(f"Season {args.season}: {len(rows)} rows for {len(games)} teams")
    print(f"Written to {out}")
    five = sorted((r for r in rows if r["situation"] == "5v5"), key=lambda r: -r["cf_pct"])
    print("\n5v5 Corsi % by team (best five and worst five):")
    for r in five[:5] + five[-5:]:
        print(
            f"  {r['team']:4s} GP {r['games_played']:3d}/{r['games_included']:3d}  CF {r['cf']:5d} CA {r['ca']:5d}  "
            f"CF% {r['cf_pct']:5.1f}  GF {r['gf']:3d} GA {r['ga']:3d}"
        )


if __name__ == "__main__":
    main()
