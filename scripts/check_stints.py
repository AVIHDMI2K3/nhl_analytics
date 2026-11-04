"""Check the built stints table three independent ways.

Run from the repo root with the `nhl` conda environment active, after build_onice.py and
build_shot_attempts.py for the season. It builds the stints in memory from the cleaned shifts
(the same code build_stints.py will use) and writes nothing:

    python scripts/check_stints.py --season 2023
    python scripts/check_stints.py --season 2024
    python scripts/check_stints.py --season 2025

Read-only. It reads data/intermediate/season=YYYY/shifts_clean.parquet and
data/metrics/season=YYYY/shot_attempts.parquet.

  A. Time on ice by strength: each skater's even-strength, power-play and shorthanded
     seconds from the stints table against the NHL's season totals. Skipped for a season
     with games that have no shift data, because the NHL's totals include those games.
  B. Power-play goals: each goal is given the strength of the stint it falls in (goals
     use the end-inclusive boundary), and each skater's power-play goals are compared with
     the boxscore's power_play_goals, per player per game. This does not use time on ice
     at all, so it checks the strength labels themselves, in every season.
  C. Agreement with the NHL's situationCode: for every attempt, the strength of the
     shooting team from the stint against the strength from the code (goalie adjusted).
"""

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

from onice import real_skaters  # noqa: E402
from stints import StintIndex, build_stints, stint_rows, strength_label  # noqa: E402

RAW_ROOT = REPO_ROOT / "data" / "raw"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"
SHIFT_COLUMNS = [
    "game_id", "player_id", "team_id", "period", "start_game_seconds", "end_game_seconds", "is_goalie",
]
STRENGTHS = ("ev", "pp", "sh")
REFERENCE_FIELDS = {"ev": "evTimeOnIce", "pp": "ppTimeOnIce", "sh": "shTimeOnIce"}


def bucket(diff):
    diff = abs(diff)
    for limit, name in ((0, "exact"), (2, "<=2 s"), (10, "<=10 s"), (60, "<=60 s")):
        if diff <= limit:
            return name
    return ">60 s"


def time_on_ice_check(stint_rows_all, season):
    reference_path = RAW_ROOT / f"season={season}" / "reference" / "skater_timeonice.json.gz"
    with gzip.open(reference_path, "rb") as handle:
        reference = {r["playerId"]: r for r in json.loads(handle.read())["data"]}
    ours = Counter()
    for row in stint_rows_all:
        for side in ("home", "away"):
            for player_id in row[f"{side}_skater_ids"]:
                ours[(player_id, row[f"{side}_strength"])] += row["seconds"]
    order = ["exact", "<=2 s", "<=10 s", "<=60 s", ">60 s"]
    print(f"\nA. Time on ice by strength vs the NHL ({len(reference)} skaters)")
    print(f"{'strength':9s}" + "".join(f"{b:>9s}" for b in order) + f"{'our total':>12s}{'NHL total':>12s}{'diff %':>9s}")
    for strength in STRENGTHS:
        counts = dict.fromkeys(order, 0)
        ours_total = nhl_total = 0
        for player_id, ref in reference.items():
            value = ours.get((player_id, strength), 0)
            ours_total += value
            nhl_total += ref[REFERENCE_FIELDS[strength]]
            counts[bucket(value - ref[REFERENCE_FIELDS[strength]])] += 1
        print(
            f"{strength:9s}" + "".join(f"{counts[b]:>9d}" for b in order)
            + f"{ours_total:>12d}{nhl_total:>12d}{100 * (ours_total - nhl_total) / nhl_total:>8.2f}%"
        )


def code_strength(row):
    if row["skaters_for"] is None:
        return None
    return strength_label(
        real_skaters(row["skaters_for"], row["goalie_for"]),
        real_skaters(row["skaters_against"], row["goalie_against"]),
    )


def main():
    parser = argparse.ArgumentParser(description="Check the stints table.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    metrics = METRICS_ROOT / f"season={args.season}"
    attempts = pq.read_table(
        metrics / "shot_attempts.parquet",
        columns=["game_id", "game_seconds", "attempt_type", "shooter_id", "is_home", "skaters_for",
                 "skaters_against", "goalie_for", "goalie_against", "matches_situation"],
    ).to_pylist()
    box = pq.read_table(
        STAGING_ROOT / f"season={args.season}" / "boxscore_players.parquet",
        columns=["game_id", "player_id", "player_group", "power_play_goals"],
    ).to_pylist()
    games_columns = pq.read_table(
        STAGING_ROOT / f"season={args.season}" / "games.parquet",
        columns=["game_id", "home_team_id", "away_team_id"],
    ).to_pydict()
    games = {
        g: {"game_id": g, "home_team_id": h, "away_team_id": a}
        for g, h, a in zip(*games_columns.values())
    }
    shift_columns = pq.read_table(
        INTERMEDIATE_ROOT / f"season={args.season}" / "shifts_clean.parquet", columns=SHIFT_COLUMNS
    ).to_pydict()
    shifts_by_game = defaultdict(list)
    for i in range(len(shift_columns["game_id"])):
        shifts_by_game[shift_columns["game_id"][i]].append(
            {name: shift_columns[name][i] for name in SHIFT_COLUMNS}
        )
    by_game = {
        game_id: stint_rows(games[game_id], build_stints(games[game_id], rows))
        for game_id, rows in shifts_by_game.items()
    }
    all_stints = [row for rows in by_game.values() for row in rows]
    indexes = {game_id: StintIndex(rows) for game_id, rows in by_game.items()}
    missing = len(set(games) - set(by_game))
    print(f"Season {args.season}: {len(by_game)} games with stints, {missing} without shift data")

    if missing:
        print("\nA. Skipped: the NHL's season totals include games we have no shifts for.")
    else:
        time_on_ice_check(all_stints, args.season)

    ours_ppg = Counter()
    outside = 0
    goals = 0
    agree, compared = Counter(), Counter()
    for row in attempts:
        index = indexes.get(row["game_id"])
        if index is None:
            continue
        goal = row["attempt_type"] == "goal"
        stint = index.at(row["game_seconds"], end_inclusive=goal)
        if stint is None:
            outside += 1
            continue
        label = stint["home_strength" if row["is_home"] else "away_strength"]
        if goal:
            goals += 1
            if label == "pp":
                ours_ppg[(row["game_id"], row["shooter_id"])] += 1
        from_code = code_strength(row)
        if from_code is not None:
            compared[label] += 1
            agree[label] += label == from_code

    official = {
        (r["game_id"], r["player_id"]): r["power_play_goals"]
        for r in box
        if r["player_group"] != "goalies" and r["power_play_goals"] is not None and r["game_id"] in by_game
    }
    exact = sum(1 for key, value in official.items() if ours_ppg.get(key, 0) == value)
    differences = sorted(
        ((abs(ours_ppg.get(key, 0) - value), key, ours_ppg.get(key, 0) - value)
         for key, value in official.items() if ours_ppg.get(key, 0) != value),
        reverse=True,
    )
    print(f"\nB. Power-play goals per player-game vs the boxscore: {exact} of {len(official)} exact "
          f"({100 * exact / len(official):.2f}%)")
    print(f"   goals checked: {goals}; our power-play goals: {sum(ours_ppg.values())}; "
          f"boxscore power-play goals: {sum(official.values())}")
    print(f"   attempts outside every stint: {outside}")
    for _, (game_id, player_id), difference in differences[:8]:
        print(f"   {game_id} {player_id} ours minus boxscore {difference:+d}")

    print("\nC. Stint strength vs situationCode strength, by stint label (shooting team)")
    for label in STRENGTHS:
        if compared[label]:
            print(f"   {label}: {100 * agree[label] / compared[label]:.2f}% agree of {compared[label]}")
    total = sum(compared.values())
    print(f"   all: {100 * sum(agree.values()) / total:.2f}% of {total}")


if __name__ == "__main__":
    main()