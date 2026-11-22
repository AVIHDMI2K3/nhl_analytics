"""Phase 4.11: build the team power-play and penalty-kill tables for one season.

Run from the repo root with the `nhl` conda environment active, after build_shot_attempts.py:

    python src/nhl_pipeline/transform/build_team_special_teams.py --season 2025

Reads  data/metrics/season=2025/{shot_attempts,stints}.parquet
       data/staging/season=2025/{events,games}.parquet
Writes data/metrics/season=2025/team_game_special_teams.parquet    one row per team and game
       data/metrics/season=2025/team_season_special_teams.parquet  one row per team

See team_special_teams.py for what the columns mean and how opportunities are counted. Needs no shift data,
so all games are included. Checked with scripts/check_team_special_teams.py.
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from build_season_display import team_abbrevs
from team_special_teams import (
    GAME_COLUMNS,
    RATE_COLUMNS,
    SEASON_COLUMNS,
    build_team_game_rows,
    build_team_season_rows,
    penalty_shot_goals,
    prepare_penalties,
    shorthanded_penalty_shot_goals,
    stint_strength,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
EVENT_COLUMNS = [
    "game_id",
    "event_type",
    "period_type",
    "game_seconds",
    "event_owner_team_id",
    "penalty_minutes",
    "situation_code",
]
STINT_COLUMNS = ["game_id", "start_game_seconds", "end_game_seconds", "home_strength", "away_strength"]
ATTEMPT_COLUMNS = [
    "game_id",
    "attempt_type",
    "team_id",
    "skaters_for",
    "skaters_against",
    "goalie_for",
    "goalie_against",
]
GAME_SCHEMA = pa.schema(
    [("season", pa.int64()), ("game_id", pa.int64()), ("team_id", pa.int64()), ("opponent_team_id", pa.int64())]
    + [(column, pa.int64()) for column in GAME_COLUMNS]
)
SEASON_SCHEMA = pa.schema(
    [("season", pa.int64()), ("team_id", pa.int64()), ("team", pa.string()), ("games_played", pa.int64())]
    + [(column, pa.int64()) for column in SEASON_COLUMNS]
    + [(column, pa.float64()) for column in RATE_COLUMNS]
)


def write_table(path, rows, schema):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")


def main():
    parser = argparse.ArgumentParser(description="Build the team power-play and penalty-kill tables.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    metrics = args.metrics_root / f"season={args.season}"
    staging = args.staging_root / f"season={args.season}"
    games = {
        g["game_id"]: g
        for g in pq.read_table(
            staging / "games.parquet", columns=["game_id", "home_team_id", "away_team_id"]
        ).to_pylist()
    }
    events = pq.read_table(staging / "events.parquet", columns=EVENT_COLUMNS).to_pylist()
    attempts = pq.read_table(metrics / "shot_attempts.parquet", columns=ATTEMPT_COLUMNS).to_pylist()

    shots = penalty_shot_goals(events, games)
    stints_by_game = {}
    for stint in pq.read_table(metrics / "stints.parquet", columns=STINT_COLUMNS).to_pylist():
        stints_by_game.setdefault(stint["game_id"], []).append(stint)
    by_strength = {}
    for shot in shots:
        key = stint_strength(stints_by_game.get(shot["game_id"], ()), shot["game_seconds"], shot["is_home"])
        by_strength[key] = by_strength.get(key, 0) + 1
    print(
        f"Penalty-shot goals outside shootouts: {len(shots)}, "
        f"by the scoring team's strength in the stint: {by_strength}"
    )
    game_rows = build_team_game_rows(
        games, prepare_penalties(events, games), attempts, shorthanded_penalty_shot_goals(shots, stints_by_game)
    )
    season_rows = build_team_season_rows(game_rows, team_abbrevs(staging))
    for row in game_rows + season_rows:
        row["season"] = args.season
    write_table(metrics / "team_game_special_teams.parquet", game_rows, GAME_SCHEMA)
    write_table(metrics / "team_season_special_teams.parquet", season_rows, SEASON_SCHEMA)

    print(f"Season {args.season}: {len(game_rows)} team-games, {len(season_rows)} teams")
    print(f"Written to {metrics}")
    print("\nPower play %, best and worst five:")
    ranked = sorted((r for r in season_rows if r["pp_pct"] is not None), key=lambda r: -r["pp_pct"])
    for r in ranked[:5] + ranked[-5:]:
        print(f"  {r['team']:4s} {r['pp_goals']:3d}/{r['pp_opportunities']:3d}  PP% {r['pp_pct']:5.1f}")
    print("\nPenalty kill %, best and worst five:")
    ranked = sorted((r for r in season_rows if r["pk_pct"] is not None), key=lambda r: -r["pk_pct"])
    for r in ranked[:5] + ranked[-5:]:
        print(
            f"  {r['team']:4s} {r['times_shorthanded'] - r['pk_goals_against']:3d}/{r['times_shorthanded']:3d}  "
            f"PK% {r['pk_pct']:5.1f}"
        )


if __name__ == "__main__":
    main()
