"""Phase 4.1: build the shot_attempts table for one season.

Run from the repo root with the `nhl` conda environment active, after build_onice.py:

    python src/nhl_pipeline/transform/build_shot_attempts.py --season 2025

Reads  data/staging/season=2025/{games,events,boxscore_players}.parquet
       data/intermediate/season=2025/event_on_ice.parquet
Writes data/metrics/season=2025/shot_attempts.parquet
       data/logs/shot_attempts_report_2025.json

It prints checks against the boxscore: goals and shots on goal per player per game.
Penalty shots are left out of our table, so a few players can differ by those.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from shot_attempts import ATTEMPT_TYPES, build_game_shot_attempts

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
LOG_DIR = REPO_ROOT / "data" / "logs"

SCHEMA = [
    ("season", "int64"),
    ("game_id", "int64"),
    ("event_id", "int64"),
    ("sort_order", "int64"),
    ("period", "int64"),
    ("period_type", "string"),
    ("seconds_in_period", "int64"),
    ("game_seconds", "int64"),
    ("attempt_type", "string"),
    ("shooter_id", "int64"),
    ("team_id", "int64"),
    ("opponent_team_id", "int64"),
    ("is_home", "bool"),
    ("shot_type", "string"),
    ("zone_code", "string"),
    ("x_raw", "float64"),
    ("y_raw", "float64"),
    ("x", "float64"),
    ("y", "float64"),
    ("goalie_id", "int64"),
    ("blocker_id", "int64"),
    ("blocker_is_teammate", "bool"),
    ("skaters_for", "int64"),
    ("skaters_against", "int64"),
    ("goalie_for", "int64"),
    ("goalie_against", "int64"),
    ("score_for", "int64"),
    ("score_against", "int64"),
    ("has_on_ice", "bool"),
    ("matches_situation", "bool"),
    ("uses_conflicting_shift", "bool"),
    ("skater_ids_for", "list_int64"),
    ("skater_ids_against", "list_int64"),
]

EVENT_COLUMNS = [
    "game_id",
    "event_id",
    "sort_order",
    "period",
    "period_type",
    "seconds_in_period",
    "game_seconds",
    "event_type",
    "situation_code",
    "event_owner_team_id",
    "x_coord",
    "y_coord",
    "zone_code",
    "shot_type",
    "shooting_player_id",
    "scoring_player_id",
    "goalie_in_net_id",
    "blocking_player_id",
    "home_defending_side",
]
ON_ICE_COLUMNS = [
    "game_id",
    "event_id",
    "home_skater_ids",
    "away_skater_ids",
    "matches_situation",
    "uses_conflicting_shift",
]


def arrow_schema():
    types = {
        "int64": pa.int64(),
        "float64": pa.float64(),
        "string": pa.string(),
        "bool": pa.bool_(),
        "list_int64": pa.list_(pa.int64()),
    }
    return pa.schema([(name, types[kind]) for name, kind in SCHEMA])


def write_table(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=arrow_schema()), path, compression="zstd")


def read_columns(path, columns):
    return pq.read_table(path, columns=columns).to_pydict()


def index_by_game(game_ids):
    positions = defaultdict(list)
    for position, game_id in enumerate(game_ids):
        positions[game_id].append(position)
    return positions


def rows_at(columns, positions):
    names = list(columns)
    return [{name: columns[name][i] for name in names} for i in positions]


def compare_with_boxscore(rows, box):
    """Per player per game: our goals and shots on goal against the boxscore's."""
    ours_goals, ours_sog = Counter(), Counter()
    for row in rows:
        key = (row["game_id"], row["shooter_id"])
        if row["attempt_type"] == "goal":
            ours_goals[key] += 1
        if row["attempt_type"] in ("goal", "shot-on-goal"):
            ours_sog[key] += 1
    games = {row["game_id"] for row in rows}
    report = {}
    for name, ours, column in (("goals", ours_goals, "goals"), ("shots on goal", ours_sog, "sog")):
        compared = exact = 0
        worst = []
        for (game_id, player_id), official in box[column].items():
            if game_id not in games:
                continue
            compared += 1
            difference = ours.get((game_id, player_id), 0) - official
            exact += difference == 0
            if difference:
                worst.append((abs(difference), game_id, player_id, difference))
        worst.sort(reverse=True)
        report[name] = (compared, exact, worst[:5])
    return report


def main():
    parser = argparse.ArgumentParser(description="Build the shot_attempts table for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--intermediate-root", type=Path, default=INTERMEDIATE_ROOT)
    parser.add_argument("--out-root", type=Path, default=METRICS_ROOT)
    parser.add_argument("--log-dir", type=Path, default=LOG_DIR)
    args = parser.parse_args()

    staging = args.staging_root / f"season={args.season}"
    game_columns = read_columns(staging / "games.parquet", ["game_id", "home_team_id", "away_team_id"])
    games = {
        game_id: {"game_id": game_id, "home_team_id": home, "away_team_id": away}
        for game_id, home, away in zip(*game_columns.values())
    }
    events = read_columns(staging / "events.parquet", EVENT_COLUMNS)
    on_ice = read_columns(args.intermediate_root / f"season={args.season}" / "event_on_ice.parquet", ON_ICE_COLUMNS)
    box_columns = read_columns(
        staging / "boxscore_players.parquet", ["game_id", "player_id", "player_group", "goals", "sog"]
    )
    box = {"goals": {}, "sog": {}}
    for game_id, player_id, group, goals, sog in zip(*box_columns.values()):
        if group == "goalies":
            continue
        if goals is not None:
            box["goals"][(game_id, player_id)] = goals
        if sog is not None:
            box["sog"][(game_id, player_id)] = sog

    event_positions = index_by_game(events["game_id"])
    on_ice_positions = index_by_game(on_ice["game_id"])

    all_rows = []
    for game_id in sorted(games):
        game_events = rows_at(events, event_positions.get(game_id, []))
        by_event = {r["event_id"]: r for r in rows_at(on_ice, on_ice_positions.get(game_id, []))}
        for row in build_game_shot_attempts(games[game_id], game_events, by_event):
            row["season"] = args.season
            all_rows.append(row)

    out = args.out_root / f"season={args.season}" / "shot_attempts.parquet"
    write_table(out, all_rows)

    by_type = Counter(r["attempt_type"] for r in all_rows)
    total = len(all_rows)
    without_on_ice = sum(1 for r in all_rows if not r["has_on_ice"])
    without_coords = sum(1 for r in all_rows if r["x"] is None)
    without_code = sum(1 for r in all_rows if r["skaters_for"] is None)
    shooter_missing = sum(1 for r in all_rows if r["shooter_id"] is None)
    blocks = [r for r in all_rows if r["attempt_type"] == "blocked-shot" and r["has_on_ice"]]
    teammate = sum(1 for r in blocks if r["blocker_is_teammate"] is True)
    opponent = sum(1 for r in blocks if r["blocker_is_teammate"] is False)
    unknown = len(blocks) - teammate - opponent
    shooter_on_ice = Counter()
    for r in all_rows:
        if r["has_on_ice"] and r["shooter_id"] is not None:
            shooter_on_ice[r["shooter_id"] in r["skater_ids_for"]] += 1

    print(f"\nShot attempts written to {out}: {total}")
    for attempt_type in ATTEMPT_TYPES:
        print(f"  {attempt_type:14s} {by_type[attempt_type]}")
    print(f"Attempts with no on-ice data (games without shifts): {without_on_ice}")
    print(f"Attempts with no coordinates or no defending side: {without_coords}")
    print(f"Attempts with no situationCode: {without_code}")
    print(f"Attempts with no shooter id: {shooter_missing}")
    checked = sum(shooter_on_ice.values())
    if checked:
        print(f"Shooter is on the ice for the owner team: {100 * shooter_on_ice[True] / checked:.2f}% of {checked}")
    print(
        f"Blocked shots, blocker on the opposing team: {opponent}, on the shooter's team: "
        f"{teammate}, not on the ice at all: {unknown}"
    )
    report = compare_with_boxscore(all_rows, box)
    for name, (compared, exact, worst) in report.items():
        pct = 100 * exact / compared if compared else 0.0
        print(f"\n{name.capitalize()} per player-game vs boxscore: {exact} of {compared} exact ({pct:.2f}%)")
        for _, game_id, player_id, difference in worst:
            print(f"  {game_id} {player_id} {difference:+d}")

    args.log_dir.mkdir(parents=True, exist_ok=True)
    (args.log_dir / f"shot_attempts_report_{args.season}.json").write_text(
        json.dumps(
            {
                "season": args.season,
                "attempts": total,
                "by_type": dict(by_type),
                "without_on_ice": without_on_ice,
                "without_coordinates": without_coords,
                "without_situation_code": without_code,
                "blocked_blocker_on_opposing_team": opponent,
                "blocked_blocker_on_shooters_team": teammate,
                "blocked_blocker_not_on_ice": unknown,
                "boxscore_exact": {k: [v[1], v[0]] for k, v in report.items()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
