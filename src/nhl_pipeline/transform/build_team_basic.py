"""Phase 4.9: build the team season basic table for one season.

Run from the repo root with the `nhl` conda environment active:

    python src/nhl_pipeline/transform/build_team_basic.py --season 2025

Reads  data/staging/season=2025/{games,boxscore_players}.parquet
Writes data/metrics/season=2025/team_season_basic.parquet

See team_basic.py for what a row holds. Regular season, every game with a boxscore.
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from build_season_display import team_abbrevs
from team_basic import COUNT_COLUMNS, build_team_basic

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
GAME_COLUMNS = [
    "game_id", "game_type", "has_boxscore", "home_team_id", "away_team_id",
    "home_score", "away_score", "last_period_type",
]
BOX_COLUMNS = [
    "game_id", "team_id", "player_group", "sog", "hits", "blocked_shots", "giveaways",
    "takeaways", "pim", "power_play_goals", "power_play_goals_against",
]
DERIVED = ["goal_diff"] + [f"{n}_per_game" for n in ("goals_for", "goals_against", "shots_for", "shots_against")]
SCHEMA = pa.schema(
    [("season", pa.int64()), ("team_id", pa.int64()), ("team", pa.string()), ("games_played", pa.int64())]
    + [(column, pa.int64()) for column in COUNT_COLUMNS]
    + [("goal_diff", pa.int64()), ("points_pct", pa.float64())]
    + [(column, pa.float64()) for column in DERIVED[1:]]
)


def write_table(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, compression="zstd")


def main():
    parser = argparse.ArgumentParser(description="Build the team season basic table.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    staging = args.staging_root / f"season={args.season}"
    games = pq.read_table(staging / "games.parquet", columns=GAME_COLUMNS).to_pylist()
    box = pq.read_table(staging / "boxscore_players.parquet", columns=BOX_COLUMNS).to_pylist()
    rows, notes = build_team_basic(games, box)
    abbrevs = team_abbrevs(staging)
    for row in rows:
        row["season"] = args.season
        row["team"] = abbrevs.get(row["team_id"], str(row["team_id"]))
    out = args.metrics_root / f"season={args.season}" / "team_season_basic.parquet"
    write_table(out, rows)

    print(f"Season {args.season}: {len(rows)} teams, games left out for a missing score: {notes['games_without_score']}")
    print(f"Written to {out}")
    print("\nStandings by points (W-L-OTL):")
    for r in sorted(rows, key=lambda r: (-r["points"], -r["regulation_wins"])):
        print(f"  {r['team']:4s} GP {r['games_played']:3d}  {r['wins']:2d}-{r['losses']:2d}-{r['ot_losses']:2d}  "
              f"PTS {r['points']:3d}  RW {r['regulation_wins']:2d}  ROW {r['row']:2d}  GF {r['goals_for']:3d}  GA {r['goals_against']:3d}")


if __name__ == "__main__":
    main()