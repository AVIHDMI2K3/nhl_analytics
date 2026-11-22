"""Phase 2: build the staging tables for one season from the raw files.

Run from the repo root with the `nhl` conda environment active:

    python src/nhl_pipeline/ingest/stage_season.py --season 2023
    python src/nhl_pipeline/ingest/stage_season.py --season 2023 --limit 5

Reads  data/raw/season=2023/...        (written by ingest_season.py)
Writes data/staging/season=2023/{games,players,events,shifts,boxscore_players}.parquet
       data/logs/staging_report_2023.json   (per-game checks)

It only reads raw files, so it is safe to rerun at any time: each run rebuilds
the season's tables from scratch.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from rawstore import (
    has_empty_marker,
    raw_path,
    read_gz_json,
    season_dir,
)
from staging import (
    check_goals,
    check_shifts,
    merge_games,
    parse_boxscore_players,
    parse_events,
    parse_roster,
    parse_schedule_week,
    parse_shifts,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_ROOT = REPO_ROOT / "data" / "raw"
DEFAULT_STAGING_ROOT = REPO_ROOT / "data" / "staging"
DEFAULT_LOG_DIR = REPO_ROOT / "data" / "logs"

BATCH_GAMES = 100  # rows are written to disk after this many games

# Column name and Parquet type. The parsers in staging.py must produce exactly
# these columns (a test checks that).
SCHEMAS = {
    "games": [
        ("game_id", "int64"),
        ("game_type", "int64"),
        ("game_date", "string"),
        ("start_time_utc", "string"),
        ("game_state", "string"),
        ("game_schedule_state", "string"),
        ("home_team_id", "int64"),
        ("home_team", "string"),
        ("home_score", "int64"),
        ("away_team_id", "int64"),
        ("away_team", "string"),
        ("away_score", "int64"),
        ("last_period_number", "int64"),
        ("last_period_type", "string"),
        ("has_events", "bool"),
        ("has_boxscore", "bool"),
        ("shift_status", "string"),  # ok | none_from_nhl | missing
        ("goals_check", "string"),  # null if events match the score
        ("shifts_backwards", "int64"),
        ("shifts_overlapping", "int64"),
    ],
    "players": [
        ("game_id", "int64"),
        ("team_id", "int64"),
        ("player_id", "int64"),
        ("first_name", "string"),
        ("last_name", "string"),
        ("sweater_number", "int64"),
        ("position_code", "string"),
    ],
    "events": [
        ("game_id", "int64"),
        ("event_id", "int64"),
        ("sort_order", "int64"),
        ("period", "int64"),
        ("period_type", "string"),
        ("time_in_period", "string"),
        ("seconds_in_period", "int64"),
        ("game_seconds", "int64"),
        ("seconds_remaining_in_period", "int64"),
        ("event_type", "string"),
        ("event_type_code", "int64"),
        ("situation_code", "string"),
        ("home_defending_side", "string"),
        ("event_owner_team_id", "int64"),
        ("x_coord", "float64"),
        ("y_coord", "float64"),
        ("zone_code", "string"),
        ("shot_type", "string"),
        ("reason", "string"),
        ("secondary_reason", "string"),
        ("shooting_player_id", "int64"),
        ("scoring_player_id", "int64"),
        ("assist1_player_id", "int64"),
        ("assist2_player_id", "int64"),
        ("goalie_in_net_id", "int64"),
        ("blocking_player_id", "int64"),
        ("hitting_player_id", "int64"),
        ("hittee_player_id", "int64"),
        ("winning_player_id", "int64"),
        ("losing_player_id", "int64"),
        ("player_id", "int64"),
        ("committed_by_player_id", "int64"),
        ("drawn_by_player_id", "int64"),
        ("served_by_player_id", "int64"),
        ("penalty_desc_key", "string"),
        ("penalty_type_code", "string"),
        ("penalty_minutes", "int64"),
        ("away_score", "int64"),
        ("home_score", "int64"),
        ("away_sog", "int64"),
        ("home_sog", "int64"),
        ("details_json", "string"),
    ],
    "shifts": [
        ("game_id", "int64"),
        ("shift_id", "int64"),
        ("player_id", "int64"),
        ("first_name", "string"),
        ("last_name", "string"),
        ("team_id", "int64"),
        ("team", "string"),
        ("period", "int64"),
        ("shift_number", "int64"),
        ("start_seconds_in_period", "int64"),
        ("end_seconds_in_period", "int64"),
        ("start_game_seconds", "int64"),
        ("end_game_seconds", "int64"),
        ("duration_seconds", "int64"),
    ],
}


def coerce_rows(table, rows):
    """Make every value match its column type, so one odd value cannot break a write.

    Strings are converted with str(), whole numbers with int(). A value that
    cannot be converted safely (for example 12.5 in an integer column) is left
    alone, and the write then fails loudly instead of silently changing data.
    """
    kinds = dict(SCHEMAS[table])
    out = []
    for row in rows:
        new = {}
        for name, kind in kinds.items():
            value = row.get(name)
            if value is None:
                new[name] = None
            elif kind == "string":
                new[name] = value if isinstance(value, str) else str(value)
            elif kind == "int64":
                if isinstance(value, float) and value.is_integer():
                    value = int(value)
                elif isinstance(value, str) and value.lstrip("-").isdigit():
                    value = int(value)
                new[name] = value
            elif kind == "float64":
                new[name] = float(value) if isinstance(value, (int, float)) else value
            else:
                new[name] = value
        out.append(new)
    return out


def arrow_schema(table):
    types = {
        "int64": pa.int64,
        "float64": pa.float64,
        "string": pa.string,
        "bool": pa.bool_,
    }
    return pa.schema([(name, types[kind]()) for name, kind in SCHEMAS[table]])


class TableWriter:
    """Writes rows to one Parquet file in batches, with a fixed schema."""

    def __init__(self, path, table):
        self.table = table
        self.schema = arrow_schema(table)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows_written = 0
        self._writer = pq.ParquetWriter(self.path, self.schema, compression="zstd")

    def write(self, rows):
        if not rows:
            return
        rows = coerce_rows(self.table, rows)
        self._writer.write_table(pa.Table.from_pylist(rows, schema=self.schema))
        self.rows_written += len(rows)

    def close(self):
        self._writer.close()


def write_inferred(path, rows):
    """Write a small table whose columns are the union of the rows' keys."""
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    table = pa.Table.from_pylist([{c: r.get(c) for c in columns} for r in rows])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")


def load_schedule_games(raw_root, season):
    folder = season_dir(raw_root, season) / "schedule"
    rows = []
    for path in sorted(folder.glob("*.json.gz")):
        rows.extend(parse_schedule_week(read_gz_json(path)))
    return {r["game_id"]: r for r in merge_games(rows)}


def raw_game_ids(raw_root, season):
    ids = []
    for folder in season_dir(raw_root, season).glob("game=*"):
        try:
            ids.append(int(folder.name.split("=", 1)[1]))
        except ValueError:
            continue
    return sorted(ids)


def stage_game(raw_root, season, game_id, schedule_row):
    """Parse one game. Returns (games_row, players, events, shifts, boxscore_players)."""
    pbp_path = raw_path(raw_root, season, game_id, "play-by-play")
    box_path = raw_path(raw_root, season, game_id, "boxscore")
    shift_path = raw_path(raw_root, season, game_id, "shiftcharts")

    players, events, shifts, box_rows = [], [], [], []
    if pbp_path.exists():
        pbp = read_gz_json(pbp_path)
        players = parse_roster(game_id, pbp)
        events = parse_events(game_id, pbp)
    if box_path.exists():
        box_rows = parse_boxscore_players(game_id, read_gz_json(box_path))
    if shift_path.exists():
        shifts = parse_shifts(game_id, read_gz_json(shift_path))
        shift_status = "ok"
    elif has_empty_marker(raw_root, season, game_id):
        shift_status = "none_from_nhl"
    else:
        shift_status = "missing"

    game = dict(schedule_row)
    game.update(
        has_events=bool(events),
        has_boxscore=bool(box_rows),
        shift_status=shift_status,
        goals_check=check_goals(game, events) if events else "no events",
        shifts_backwards=None,
        shifts_overlapping=None,
    )
    if shifts:
        found = check_shifts(shifts)
        game["shifts_backwards"] = found["backwards"]
        game["shifts_overlapping"] = found["overlaps"]
    return game, players, events, shifts, box_rows


def main():
    parser = argparse.ArgumentParser(description="Build the staging tables for one season from the raw files.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--limit", type=int, help="stage only the first N games (a trial run)")
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING_ROOT)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    args = parser.parse_args()

    schedule = load_schedule_games(args.raw_root, args.season)
    if not schedule:
        sys.exit(
            f"No schedule files under {season_dir(args.raw_root, args.season) / 'schedule'}. "
            "Run ingest_season.py for this season first."
        )
    game_ids = [g for g in raw_game_ids(args.raw_root, args.season) if g in schedule]
    if args.limit:
        game_ids = game_ids[: args.limit]
    print(f"Staging {len(game_ids)} games for season {args.season} ...")

    out = args.staging_root / f"season={args.season}"
    writers = {table: TableWriter(out / f"{table}.parquet", table) for table in ("players", "events", "shifts")}
    games_rows, box_all = [], []
    pending = {"players": [], "events": [], "shifts": []}
    try:
        for index, game_id in enumerate(game_ids, start=1):
            game, players, events, shifts, box_rows = stage_game(args.raw_root, args.season, game_id, schedule[game_id])
            games_rows.append(game)
            box_all.extend(box_rows)
            pending["players"].extend(players)
            pending["events"].extend(events)
            pending["shifts"].extend(shifts)
            if index % BATCH_GAMES == 0 or index == len(game_ids):
                for table, rows in pending.items():
                    writers[table].write(rows)
                    rows.clear()
                print(f"  {index}/{len(game_ids)} games")
    finally:
        for writer in writers.values():
            writer.close()

    games_writer = TableWriter(out / "games.parquet", "games")
    games_writer.write(games_rows)
    games_writer.close()
    if box_all:
        write_inferred(out / "boxscore_players.parquet", box_all)

    report = {
        "season": args.season,
        "games": len(games_rows),
        "rows": {t: w.rows_written for t, w in writers.items()}
        | {"games": len(games_rows), "boxscore_players": len(box_all)},
        "shift_status": dict(Counter(g["shift_status"] for g in games_rows)),
        "games_without_events": [g["game_id"] for g in games_rows if not g["has_events"]],
        "games_without_boxscore": [g["game_id"] for g in games_rows if not g["has_boxscore"]],
        "goal_mismatches": {g["game_id"]: g["goals_check"] for g in games_rows if g["goals_check"]},
        "games_with_backwards_shifts": [g["game_id"] for g in games_rows if g["shifts_backwards"]],
        "games_with_overlapping_shifts": [g["game_id"] for g in games_rows if g["shifts_overlapping"]],
    }
    args.log_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.log_dir / f"staging_report_{args.season}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nTables written to {out}")
    print(f"Rows: {report['rows']}")
    print(f"Shift data: {report['shift_status']}")
    print(f"Games without events: {len(report['games_without_events'])}")
    print(f"Games without boxscore: {len(report['games_without_boxscore'])}")
    print(f"Goal mismatches (events vs final score): {len(report['goal_mismatches'])}")
    print(f"Games with backwards shifts: {len(report['games_with_backwards_shifts'])}")
    print(f"Games with overlapping shifts: {len(report['games_with_overlapping_shifts'])}")
    print(f"Details: {report_path}")


if __name__ == "__main__":
    main()
