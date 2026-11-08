"""Phase 4.3: build the base tables for one season.

Run from the repo root with the `nhl` conda environment active, after build_onice.py,
build_shot_attempts.py and build_stints.py:

    python src/nhl_pipeline/transform/build_base_tables.py --season 2025

Reads  data/staging/season=2025/games.parquet
       data/metrics/season=2025/{stints,shot_attempts}.parquet
Writes data/metrics/season=2025/player_game_strength.parquet
       data/metrics/season=2025/team_game_strength.parquet
       data/logs/base_tables_report_2025.json   counts, the games left out for lack of shift
                                                data, and every goalie-as-shooter and
                                                shooter-not-on-the-ice case

See base_tables.py for what a row holds. The logic was checked with
scripts/check_base_tables.py against the NHL's time on ice and the boxscore before this
script was written. Games without shift data have no stints and so no rows.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from base_tables import (
    KINDS,
    PLAYER_COUNT_COLUMNS,
    STATE_COLUMNS,
    TEAM_COUNT_COLUMNS,
    build_game_tables,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
LOG_DIR = REPO_ROOT / "data" / "logs"
STRENGTHS = ("ev", "pp", "sh")
EVENT_COLUMNS = [
    "game_id", "event_type", "period_type", "game_seconds", "event_owner_team_id",
    "assist1_player_id", "assist2_player_id", "hitting_player_id", "hittee_player_id", "player_id",
    "winning_player_id", "losing_player_id", "committed_by_player_id", "drawn_by_player_id",
    "penalty_minutes",
]
ATTEMPT_COLUMNS = [
    "game_id", "event_id", "game_seconds", "attempt_type", "shooter_id", "blocker_id",
    "blocker_is_teammate", "is_home", "skaters_for", "skaters_against", "goalie_for", "goalie_against",
]

STATE_TYPES = [("strength", pa.string())] + [(name, pa.int64()) for name in STATE_COLUMNS[1:]]
SCHEMAS = {
    "player_game_strength": pa.schema(
        [("season", pa.int64()), ("game_id", pa.int64()), ("player_id", pa.int64()), ("team_id", pa.int64())]
        + STATE_TYPES
        + [(name, pa.int64()) for name in PLAYER_COUNT_COLUMNS]
    ),
    "team_game_strength": pa.schema(
        [("season", pa.int64()), ("game_id", pa.int64()), ("team_id", pa.int64())]
        + STATE_TYPES
        + [(name, pa.int64()) for name in TEAM_COUNT_COLUMNS]
    ),
}


def write_table(path, rows, table):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMAS[table]), path, compression="zstd")


def group_by_game(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["game_id"]].append(row)
    return groups


def main():
    parser = argparse.ArgumentParser(description="Build the base tables for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    parser.add_argument("--log-dir", type=Path, default=LOG_DIR)
    args = parser.parse_args()

    metrics = args.metrics_root / f"season={args.season}"
    games = {
        g["game_id"]: g
        for g in pq.read_table(
            args.staging_root / f"season={args.season}" / "games.parquet",
            columns=["game_id", "home_team_id", "away_team_id"],
        ).to_pylist()
    }
    stints = group_by_game(pq.read_table(metrics / "stints.parquet").to_pylist())
    attempts = group_by_game(
        pq.read_table(metrics / "shot_attempts.parquet", columns=ATTEMPT_COLUMNS).to_pylist()
    )

    events = group_by_game(
        pq.read_table(args.staging_root / f"season={args.season}" / "events.parquet", columns=EVENT_COLUMNS).to_pylist()
    )

    player_rows, team_rows = [], []
    records = []
    notes = Counter()
    for game_id in sorted(stints):
        players, teams, game_notes = build_game_tables(
            games[game_id], stints[game_id], attempts.get(game_id, []), events.get(game_id, []), records
        )
        for row in players + teams:
            row["season"] = args.season
        player_rows.extend(players)
        team_rows.extend(teams)
        notes.update(game_notes)

    write_table(metrics / "player_game_strength.parquet", player_rows, "player_game_strength")
    write_table(metrics / "team_game_strength.parquet", team_rows, "team_game_strength")

    seconds = Counter()
    for row in player_rows:
        seconds[row["strength"]] += row["seconds"]
    counted = Counter()
    for row in team_rows:
        for kind in KINDS:
            counted[kind] += row[f"for_{kind}"]
    print(f"Season {args.season}: {len(stints)} games, {len(games) - len(stints)} without shift data (no rows)")
    print(f"Written to {metrics}")
    print(f"  player_game_strength: {len(player_rows)} rows")
    print(f"  team_game_strength:   {len(team_rows)} rows")
    print("Player seconds by strength: " + ", ".join(f"{s} {seconds[s]}" for s in STRENGTHS))
    print("Attempts counted: " + ", ".join(f"{k} {counted[k]}" for k in KINDS))
    print(f"Attempts outside every stint (not counted): {notes['attempts_outside_stints']}")
    print(f"Attempts counted under the situationCode state: {notes['state_from_code']}, "
          f"of which different from the stint's state: {notes['state_differs_from_stint']}")
    print(f"Shooter not on the ice in his stint (credited anyway): {notes['shooter_not_on_ice']}")
    print(f"Goalie as shooter (counted for the team and skaters, no skater row): {notes['goalie_shooter']}")
    print(f"Goalies named in other events (no skater row): {notes['goalie_event']}")
    print(f"Players not on the ice in an event, placed by the owner team: {notes['actor_not_on_ice']}")
    print(f"Events outside every stint (not counted): {notes['events_outside_stints']}")

    args.log_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "season": args.season,
        "games_with_rows": len(stints),
        "games_without_shift_data": sorted(set(games) - set(stints)),
        "player_rows": len(player_rows),
        "team_rows": len(team_rows),
        "player_seconds_by_strength": {s: seconds[s] for s in STRENGTHS},
        "attempts_counted": dict(counted),
        "notes": dict(notes),
        "cases": records,
    }
    report_path = args.log_dir / f"base_tables_report_{args.season}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()