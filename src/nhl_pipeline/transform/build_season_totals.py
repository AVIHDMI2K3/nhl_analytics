"""Phase 4.5: build the skater and goalie season totals from the boxscore, for one season.

Run from the repo root with the `nhl` conda environment active:

    python src/nhl_pipeline/transform/build_season_totals.py --season 2025

Reads  data/staging/season=2025/{games,boxscore_players}.parquet
Writes data/metrics/season=2025/player_season_totals.parquet      (skaters)
       data/metrics/season=2025/goalie_season_totals.parquet      (goalies)

See season_totals.py for what a row holds. Regular-season games only.
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from season_totals import (
    GOALIE_COLUMNS,
    GOALIE_SUM_COLUMNS,
    REGULAR_SEASON,
    SUM_COLUMNS,
    build_goalie_season_totals,
    build_player_season_totals,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
# the boxscore's own columns; the goalie counts (wins, shutouts, ...) are worked out, not stored there
BOX_COLUMNS = list(
    dict.fromkeys(
        ["game_id", "team_id", "player_group", "player_id", "name", "position", "starter", "decision"]
        + list(SUM_COLUMNS)
        + list(GOALIE_SUM_COLUMNS)
    )
)
IDENTITY_FIELDS = [
    ("season", pa.int64()),
    ("player_id", pa.int64()),
    ("team_id", pa.int64()),
    ("name", pa.string()),
    ("position", pa.string()),
    ("games_played", pa.int64()),
    ("first_game_date", pa.string()),
]
SCHEMA = pa.schema(IDENTITY_FIELDS + [(column, pa.int64()) for column in SUM_COLUMNS])
GOALIE_SCHEMA = pa.schema(IDENTITY_FIELDS + [(column, pa.int64()) for column in GOALIE_COLUMNS])


def write_table(path, rows, schema=SCHEMA):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")


def main():
    parser = argparse.ArgumentParser(description="Build skater and goalie season totals from the boxscore.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    staging = args.staging_root / f"season={args.season}"
    games = pq.read_table(
        staging / "games.parquet", columns=["game_id", "game_type", "has_boxscore", "game_date"]
    ).to_pylist()
    regular = {
        g["game_id"]: str(g["game_date"]) for g in games if g["game_type"] == REGULAR_SEASON and g["has_boxscore"]
    }
    box = pq.read_table(staging / "boxscore_players.parquet", columns=BOX_COLUMNS).to_pylist()

    rows = build_player_season_totals(box, set(regular), regular)
    for row in rows:
        row["season"] = args.season
    out = args.metrics_root / f"season={args.season}" / "player_season_totals.parquet"
    write_table(out, rows)
    print(f"Season {args.season}: {len(regular)} regular-season games with a boxscore")
    print(f"  player_season_totals: {len(rows)} rows ({len({r['player_id'] for r in rows})} skaters)")
    print(
        f"  goals {sum(r['goals'] for r in rows)}, assists {sum(r['assists'] for r in rows)}, "
        f"games played (sum) {sum(r['games_played'] for r in rows)}"
    )
    print(f"Written to {out}")

    goalie_rows = build_goalie_season_totals(box, set(regular), regular)
    for row in goalie_rows:
        row["season"] = args.season
    goalie_out = args.metrics_root / f"season={args.season}" / "goalie_season_totals.parquet"
    write_table(goalie_out, goalie_rows, GOALIE_SCHEMA)
    played = [r for r in goalie_rows if r["games_played"]]
    print(f"  goalie_season_totals: {len(goalie_rows)} rows ({len({r['player_id'] for r in played})} goalies played)")
    print(
        f"  wins {sum(r['wins'] for r in goalie_rows)}, losses {sum(r['losses'] for r in goalie_rows)}, "
        f"overtime losses {sum(r['ot_losses'] for r in goalie_rows)}, "
        f"shutouts {sum(r['shutouts'] for r in goalie_rows)}, "
        f"shots against {sum(r['shots_against'] for r in goalie_rows)}"
    )
    print(f"Written to {goalie_out}")


if __name__ == "__main__":
    main()
