"""Phase 4.10: build the power-play and penalty-kill skater table for one season.

Run from the repo root with the `nhl` conda environment active, after build_base_tables.py and
build_season_totals.py:

    python src/nhl_pipeline/transform/build_player_special_teams.py --season 2025

Reads  data/metrics/season=2025/{player_game_strength,team_game_strength,player_season_totals,shot_attempts}.parquet
       data/staging/season=2025/{events,players,games}.parquet
Writes data/metrics/season=2025/player_season_special_teams.parquet

One row per skater, team (or combined row for a traded player) and situation (pp, sh); see special_teams.py.
Individual counts come from the play-by-play with the strength from the NHL's situation code (all games);
time on ice, team share and on-ice goals come from the shifts (games with shift data).
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from build_season_display import full_names, team_abbrevs
from special_teams import (
    COUNT_COLUMNS,
    RATE_COLUMNS,
    build_special_teams_counts,
    build_special_teams_display,
    goal_assists,
)
from team_special_teams import penalty_shot_goals, shorthanded_penalty_shot_attempts

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
PLAYER_COLUMNS = ["game_id", "player_id", "team_id", "strength", "seconds", "for_goal", "against_goal"]
TEAM_COLUMNS = ["game_id", "team_id", "strength", "seconds"]
ATTEMPT_COLUMNS = [
    "game_id",
    "event_id",
    "attempt_type",
    "shooter_id",
    "team_id",
    "skaters_for",
    "skaters_against",
    "goalie_for",
    "goalie_against",
]
EVENT_COLUMNS = [
    "game_id",
    "event_id",
    "event_type",
    "period_type",
    "game_seconds",
    "event_owner_team_id",
    "situation_code",
    "scoring_player_id",
    "assist1_player_id",
    "assist2_player_id",
]
STINT_COLUMNS = ["game_id", "start_game_seconds", "end_game_seconds", "home_strength", "away_strength"]
SCHEMA = pa.schema(
    [
        ("season", pa.int64()),
        ("player_id", pa.int64()),
        ("name", pa.string()),
        ("position", pa.string()),
        ("kind", pa.string()),
        ("team_id", pa.int64()),
        ("team", pa.string()),
        ("teams", pa.string()),
        ("situation", pa.string()),
        ("games_played", pa.int64()),
        ("games_included", pa.int64()),
    ]
    + [(column, pa.int64()) for column in COUNT_COLUMNS]
    + [(column, pa.float64()) for column in RATE_COLUMNS]
)


def write_table(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, compression="zstd")


def main():
    parser = argparse.ArgumentParser(description="Build the power-play and penalty-kill skater table.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    metrics = args.metrics_root / f"season={args.season}"
    staging = args.staging_root / f"season={args.season}"
    player_rows = pq.read_table(metrics / "player_game_strength.parquet", columns=PLAYER_COLUMNS).to_pylist()
    team_rows = pq.read_table(metrics / "team_game_strength.parquet", columns=TEAM_COLUMNS).to_pylist()
    season_rows = pq.read_table(metrics / "player_season_totals.parquet").to_pylist()
    attempts = pq.read_table(metrics / "shot_attempts.parquet", columns=ATTEMPT_COLUMNS).to_pylist()
    events = pq.read_table(staging / "events.parquet", columns=EVENT_COLUMNS).to_pylist()
    assists = goal_assists(events)
    # Penalty-shot goals are not in shot_attempts; the NHL counts those scored shorthanded as shorthanded goals.
    games = {
        g["game_id"]: g
        for g in pq.read_table(
            staging / "games.parquet", columns=["game_id", "home_team_id", "away_team_id"]
        ).to_pylist()
    }
    stints_by_game = {}
    for stint in pq.read_table(metrics / "stints.parquet", columns=STINT_COLUMNS).to_pylist():
        stints_by_game.setdefault(stint["game_id"], []).append(stint)
    attempts += shorthanded_penalty_shot_attempts(penalty_shot_goals(events, games), stints_by_game)

    totals, games_included = build_special_teams_counts(player_rows, team_rows, attempts, assists)
    rows = build_special_teams_display(totals, games_included, season_rows, full_names(staging), team_abbrevs(staging))
    for row in rows:
        row["season"] = args.season
    out = metrics / "player_season_special_teams.parquet"
    write_table(out, rows)

    print(f"Season {args.season}: {len(rows)} rows ({len({r['player_id'] for r in rows})} skaters)")
    print(f"Written to {out}")
    shown = [r for r in rows if r["kind"] != "team" or r["teams"] == r["team"]]
    pp = sorted(
        (r for r in shown if r["situation"] == "pp" and r["seconds"] >= 3600), key=lambda r: -r["points_per_60"]
    )
    print("\nPower play, most points per 60 (at least 60 minutes):")
    for r in pp[:10]:
        print(
            f"  {r['name']:24s} {r['team']:4s} PP TOI {r['seconds'] / 60:6.1f} min "
            f"({r['team_share_pct']:4.1f}% of team)  "
            f"G {r['goals']:2d} A {r['assists']:2d} P {r['points']:2d}  "
            f"P/60 {r['points_per_60']:.2f}  SH% {r['shooting_pct'] or 0:.1f}"
        )
    sh = sorted((r for r in shown if r["situation"] == "sh" and r["seconds"] >= 3600), key=lambda r: -r["seconds"])
    print("\nPenalty kill, most time on ice:")
    for r in sh[:10]:
        print(
            f"  {r['name']:24s} {r['team']:4s} PK TOI {r['seconds'] / 60:6.1f} min "
            f"({r['team_share_pct']:4.1f}% of team)  "
            f"GP {r['games_played']:3d}/{r['games_included']:3d}  SHG {r['goals']}  GA/60 {r['ga_per_60']:.2f}"
        )


if __name__ == "__main__":
    main()
