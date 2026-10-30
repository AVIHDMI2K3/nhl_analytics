"""Phase 3: build the on-ice tables for one season from the staging tables.

Run from the repo root with the `nhl` conda environment active:

    python src/nhl_pipeline/transform/build_onice.py --season 2023 --limit 20
    python src/nhl_pipeline/transform/build_onice.py --season 2023

Reads  data/staging/season=2023/{games,events,shifts,boxscore_players}.parquet
Writes data/intermediate/season=2023/
           shifts_clean.parquet         shifts without duplicates or overlaps, goalies marked, ambiguous ones flagged
           event_on_ice.parquet         one row per event: who was on the ice, and whether the
                                        counts agree with situationCode
           player_game_plus_minus.parquet   plus/minus per skater per game, from our on-ice data
       data/logs/onice_report_2023.json

It prints how often our on-ice counts agree with situationCode, and how our
plus/minus compares with the official boxscore, which is the end-to-end check
that the join is right. Games without shift data are skipped.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from onice import build_event_on_ice, clean_shifts, game_plus_minus, shifts_of_game_teams

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"
LOG_DIR = REPO_ROOT / "data" / "logs"

BATCH_GAMES = 100

SCHEMAS = {
    "shifts_clean": [
        ("game_id", "int64"),
        ("player_id", "int64"),
        ("team_id", "int64"),
        ("period", "int64"),
        ("start_game_seconds", "int64"),
        ("end_game_seconds", "int64"),
        ("is_goalie", "bool"),
        ("has_conflict", "bool"),
    ],
    "event_on_ice": [
        ("game_id", "int64"),
        ("event_id", "int64"),
        ("sort_order", "int64"),
        ("period", "int64"),
        ("game_seconds", "int64"),
        ("event_type", "string"),
        ("event_owner_team_id", "int64"),
        ("rule", "string"),
        ("situation_code", "string"),
        ("away_goalie_code", "int64"),
        ("away_skaters_code", "int64"),
        ("home_skaters_code", "int64"),
        ("home_goalie_code", "int64"),
        ("home_skaters_on_ice", "int64"),
        ("away_skaters_on_ice", "int64"),
        ("home_goalies_on_ice", "int64"),
        ("away_goalies_on_ice", "int64"),
        ("matches_situation", "bool"),
        ("uses_conflicting_shift", "bool"),
        ("home_skater_ids", "list_int64"),
        ("away_skater_ids", "list_int64"),
        ("home_goalie_ids", "list_int64"),
        ("away_goalie_ids", "list_int64"),
    ],
    "player_game_plus_minus": [
        ("game_id", "int64"),
        ("player_id", "int64"),
        ("plus_minus", "int64"),
    ],
}


def arrow_schema(table):
    types = {
        "int64": pa.int64(),
        "string": pa.string(),
        "bool": pa.bool_(),
        "list_int64": pa.list_(pa.int64()),
    }
    return pa.schema([(name, types[kind]) for name, kind in SCHEMAS[table]])


class TableWriter:
    """Writes rows to one Parquet file in batches, with a fixed schema."""

    def __init__(self, path, table):
        self.schema = arrow_schema(table)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows_written = 0
        self._writer = pq.ParquetWriter(self.path, self.schema, compression="zstd")

    def write(self, rows):
        if not rows:
            return
        self._writer.write_table(pa.Table.from_pylist(rows, schema=self.schema))
        self.rows_written += len(rows)

    def close(self):
        self._writer.close()


def read_columns(path, columns):
    """Read some columns of a Parquet file as {column: list of values}."""
    return pq.read_table(path, columns=columns).to_pydict()


def index_by_game(game_ids):
    positions = defaultdict(list)
    for position, game_id in enumerate(game_ids):
        positions[game_id].append(position)
    return positions


def rows_at(columns, positions):
    names = list(columns)
    return [{name: columns[name][i] for name in names} for i in positions]


def shift_rows_for_output(shifts):
    return [
        {
            "game_id": s["game_id"],
            "player_id": s["player_id"],
            "team_id": s["team_id"],
            "period": s["period"],
            "start_game_seconds": s["start"],
            "end_game_seconds": s["end"],
            "is_goalie": s["is_goalie"],
            "has_conflict": s["has_conflict"],
        }
        for s in shifts
    ]


def compare_plus_minus(box_plus_minus, ours, games_done):
    """Compare our plus/minus with the boxscore for skaters in the games we built."""
    differences = Counter()
    worst = []
    compared = 0
    for (game_id, player_id), official in box_plus_minus.items():
        if game_id not in games_done:
            continue
        compared += 1
        difference = ours.get((game_id, player_id), 0) - official
        differences[difference] += 1
        if difference:
            worst.append((abs(difference), game_id, player_id, difference))
    worst.sort(reverse=True)
    return compared, differences, worst[:10]


def main():
    parser = argparse.ArgumentParser(description="Build the on-ice tables for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--limit", type=int, help="build only the first N games (a trial run)")
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--out-root", type=Path, default=INTERMEDIATE_ROOT)
    parser.add_argument("--log-dir", type=Path, default=LOG_DIR)
    args = parser.parse_args()

    staging = args.staging_root / f"season={args.season}"
    game_columns = read_columns(
        staging / "games.parquet",
        ["game_id", "home_team_id", "away_team_id", "shift_status"],
    )
    games = {
        game_id: {"game_id": game_id, "home_team_id": home, "away_team_id": away}
        for game_id, home, away, status in zip(
            game_columns["game_id"],
            game_columns["home_team_id"],
            game_columns["away_team_id"],
            game_columns["shift_status"],
        )
        if status == "ok"
    }
    skipped = sum(1 for status in game_columns["shift_status"] if status != "ok")
    game_ids = sorted(games)
    if args.limit:
        game_ids = game_ids[: args.limit]
    print(f"Building {len(game_ids)} games for season {args.season} ({skipped} skipped: no shift data)")

    events = read_columns(
        staging / "events.parquet",
        [
            "game_id", "event_id", "sort_order", "period", "period_type", "game_seconds",
            "event_type", "situation_code", "event_owner_team_id",
        ],
    )
    shifts = read_columns(
        staging / "shifts.parquet",
        [
            "game_id", "player_id", "team_id", "period", "shift_number", "shift_id",
            "start_game_seconds", "end_game_seconds",
        ],
    )
    box = read_columns(
        staging / "boxscore_players.parquet",
        ["game_id", "player_id", "player_group", "plus_minus"],
    )
    event_positions = index_by_game(events["game_id"])
    shift_positions = index_by_game(shifts["game_id"])
    goalie_ids = defaultdict(set)
    box_plus_minus = {}
    for game_id, player_id, group, plus_minus in zip(
        box["game_id"], box["player_id"], box["player_group"], box["plus_minus"]
    ):
        if group == "goalies":
            goalie_ids[game_id].add(player_id)
        elif plus_minus is not None:
            box_plus_minus[(game_id, player_id)] = plus_minus

    out = args.out_root / f"season={args.season}"
    writers = {
        "shifts_clean": TableWriter(out / "shifts_clean.parquet", "shifts_clean"),
        "event_on_ice": TableWriter(out / "event_on_ice.parquet", "event_on_ice"),
    }
    pending = {"shifts_clean": [], "event_on_ice": []}

    totals = Counter()
    by_type = defaultdict(Counter)
    per_game_mismatches = Counter()
    ours_plus_minus = {}
    games_done = set()
    try:
        for index, game_id in enumerate(game_ids, start=1):
            game = games[game_id]
            all_shift_rows = rows_at(shifts, shift_positions.get(game_id, []))
            shift_rows = shifts_of_game_teams(all_shift_rows, game)
            totals["shift_rows_other_teams"] += len(all_shift_rows) - len(shift_rows)
            clean = clean_shifts(shift_rows, goalie_ids[game_id])
            totals["shift_rows"] += len(shift_rows)
            totals["shift_rows_dropped"] += len(shift_rows) - len(clean)
            rows = build_event_on_ice(game, rows_at(events, event_positions.get(game_id, [])), clean)
            pending["shifts_clean"].extend(shift_rows_for_output(clean))
            pending["event_on_ice"].extend(rows)
            games_done.add(game_id)

            for player_id, value in game_plus_minus(game, rows).items():
                ours_plus_minus[(game_id, player_id)] = value
            for row in rows:
                totals["events"] += 1
                by_type[row["event_type"]]["events"] += 1
                if row["uses_conflicting_shift"]:
                    totals["conflict_events"] += 1
                if row["matches_situation"] is None:
                    totals["no_code"] += 1
                    continue
                by_type[row["event_type"]]["compared"] += 1
                if row["matches_situation"]:
                    totals["matches"] += 1
                    by_type[row["event_type"]]["matches"] += 1
                else:
                    totals["mismatches"] += 1
                    per_game_mismatches[game_id] += 1
                    if row["uses_conflicting_shift"]:
                        totals["conflict_mismatches"] += 1

            if index % BATCH_GAMES == 0 or index == len(game_ids):
                for table, batch in pending.items():
                    writers[table].write(batch)
                    batch.clear()
                print(f"  {index}/{len(game_ids)} games")
    finally:
        for writer in writers.values():
            writer.close()

    plus_minus_rows = [
        {"game_id": g, "player_id": p, "plus_minus": v}
        for (g, p), v in sorted(ours_plus_minus.items())
    ]
    pm_writer = TableWriter(out / "player_game_plus_minus.parquet", "player_game_plus_minus")
    pm_writer.write(plus_minus_rows)
    pm_writer.close()

    compared = totals["matches"] + totals["mismatches"]
    agreement = 100 * totals["matches"] / compared if compared else 0.0
    print(f"\nTables written to {out}")
    print(
        f"Shift rows dropped as duplicates or overlaps: {totals['shift_rows_dropped']} "
        f"of {totals['shift_rows']}"
    )
    print(f"Shift rows removed because the team is not in the game: {totals['shift_rows_other_teams']}")
    print(f"Events: {totals['events']}  (no situationCode: {totals['no_code']})")
    print(f"On-ice counts agree with situationCode: {agreement:.2f}% of {compared} events")
    print(
        f"Events that use a conflicting shift: {totals['conflict_events']}; "
        f"of the {totals['mismatches']} disagreements, {totals['conflict_mismatches']} use one"
    )
    print("\nAgreement by event type:")
    for event_type, counter in sorted(by_type.items(), key=lambda kv: -kv[1]["events"]):
        if counter["compared"]:
            share = 100 * counter["matches"] / counter["compared"]
            print(f"  {event_type:20s} {counter['events']:>8} events  {share:6.2f}% agree")

    pm_compared, differences, worst = compare_plus_minus(box_plus_minus, ours_plus_minus, games_done)
    print(f"\nPlus/minus vs boxscore ({pm_compared} skater-games):")
    for difference in sorted(differences, key=lambda d: (abs(d), d))[:7]:
        share = 100 * differences[difference] / pm_compared
        label = "exact match" if difference == 0 else f"ours {difference:+d}"
        print(f"  {label:14s} {differences[difference]:>8}  ({share:.2f}%)")
    if worst:
        print("Largest differences (game_id, player_id, ours minus boxscore):")
        for _, game_id, player_id, difference in worst:
            print(f"  {game_id} {player_id} {difference:+d}")

    report = {
        "season": args.season,
        "games_built": len(games_done),
        "games_skipped_no_shifts": skipped,
        "shift_rows": totals["shift_rows"],
        "shift_rows_dropped": totals["shift_rows_dropped"],
        "shift_rows_other_teams": totals["shift_rows_other_teams"],
        "events": totals["events"],
        "events_without_code": totals["no_code"],
        "agreement_pct": round(agreement, 3),
        "events_using_conflicting_shift": totals["conflict_events"],
        "mismatches_using_conflicting_shift": totals["conflict_mismatches"],
        "agreement_by_event_type": {
            t: {"events": c["events"], "compared": c["compared"], "matches": c["matches"]}
            for t, c in by_type.items()
        },
        "games_with_most_disagreements": per_game_mismatches.most_common(10),
        "plus_minus": {
            "skater_games": pm_compared,
            "difference_counts": {str(d): n for d, n in sorted(differences.items())},
        },
    }
    args.log_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.log_dir / f"onice_report_{args.season}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nDetails: {report_path}")


if __name__ == "__main__":
    main()