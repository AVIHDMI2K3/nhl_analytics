"""Phase 4.2: build the stints table for one season.

Run from the repo root with the `nhl` conda environment active, after build_onice.py:

    python src/nhl_pipeline/transform/build_stints.py --season 2025

Reads  data/staging/season=2025/games.parquet
       data/intermediate/season=2025/shifts_clean.parquet
Writes data/metrics/season=2025/stints.parquet

One row per stint: a stretch of one period in which nobody changes on the ice, with
both lineups, each side's real skaters and each side's strength (ev, pp, sh). Games
without shift data have no stints. See stints.py for how strength is decided; on
2023 and 2025 it matches the NHL's even-strength, power-play and shorthanded time on
ice to within about 0.03%, 0.2% and 0.2%.
"""

import argparse
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from stints import build_stints, stint_rows

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"

SCHEMA = [
    ("season", "int64"),
    ("game_id", "int64"),
    ("period", "int64"),
    ("start_game_seconds", "int64"),
    ("end_game_seconds", "int64"),
    ("seconds", "int64"),
    ("home_skater_ids", "list_int64"),
    ("away_skater_ids", "list_int64"),
    ("home_goalie_ids", "list_int64"),
    ("away_goalie_ids", "list_int64"),
    ("home_real_skaters", "int64"),
    ("away_real_skaters", "int64"),
    ("home_strength", "string"),
    ("away_strength", "string"),
]
SHIFT_COLUMNS = [
    "game_id", "player_id", "team_id", "period", "start_game_seconds", "end_game_seconds", "is_goalie",
]


def arrow_schema():
    types = {"int64": pa.int64(), "string": pa.string(), "list_int64": pa.list_(pa.int64())}
    return pa.schema([(name, types[kind]) for name, kind in SCHEMA])


def write_table(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=arrow_schema()), path, compression="zstd")


def main():
    parser = argparse.ArgumentParser(description="Build the stints table for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--intermediate-root", type=Path, default=INTERMEDIATE_ROOT)
    parser.add_argument("--out-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    games_columns = pq.read_table(
        args.staging_root / f"season={args.season}" / "games.parquet",
        columns=["game_id", "home_team_id", "away_team_id"],
    ).to_pydict()
    games = {
        game_id: {"game_id": game_id, "home_team_id": home, "away_team_id": away}
        for game_id, home, away in zip(
            games_columns["game_id"], games_columns["home_team_id"], games_columns["away_team_id"]
        )
    }
    shift_columns = pq.read_table(
        args.intermediate_root / f"season={args.season}" / "shifts_clean.parquet",
        columns=SHIFT_COLUMNS,
    ).to_pydict()
    by_game = defaultdict(list)
    for i in range(len(shift_columns["game_id"])):
        by_game[shift_columns["game_id"][i]].append({name: shift_columns[name][i] for name in SHIFT_COLUMNS})

    rows = []
    for game_id in sorted(by_game):
        for row in stint_rows(games[game_id], build_stints(games[game_id], by_game[game_id])):
            row["season"] = args.season
            rows.append(row)

    out = args.out_root / f"season={args.season}" / "stints.parquet"
    write_table(out, rows)

    seconds = defaultdict(int)
    for row in rows:
        for side in ("home", "away"):
            seconds[row[f"{side}_strength"]] += row["seconds"]
    total = sum(seconds.values())
    print(f"Stints written to {out}: {len(rows)} in {len(by_game)} games")
    print(f"Games without shift data (no stints): {len(games) - len(by_game)}")
    print("Team-seconds by strength: " + ", ".join(
        f"{s} {seconds[s]} ({100 * seconds[s] / total:.1f}%)" for s in ("ev", "pp", "sh")
    ))


if __name__ == "__main__":
    main()