"""Check the goalie season totals against the NHL's own goalie report, before anything is built.

Run from the repo root with the `nhl` conda environment active, after ingest_reference.py:

    python scripts/check_goalie_totals.py --season 2025

The totals are worked out in memory from the boxscore (season_totals.build_goalie_season_totals),
nothing is written. Per goalie (all teams added up) they are compared with the NHL's goalie summary
(data/raw/season=YYYY/reference/goalie_summary.json.gz): games played and started, wins, losses,
overtime losses, shots against, saves, goals against, time on ice, save percentage and
goals-against average. Also checked: the strength splits add up to the totals, and five ways to count
shutouts, to see which one the NHL uses:
  1  no goals against in a game he played
  2  as 1, and he got the win
  3  as 2, and he was the only goalie of his team with time on ice
  4  as 3, and the game did not go to a shootout
  5  as 1, and he was the only goalie of his team with time on ice, and he did not lose in regulation
     (a win, or a shootout loss)
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

from season_totals import (  # noqa: E402
    GOALIE_SUM_COLUMNS, REGULAR_SEASON, build_goalie_season_totals,
)

RAW_ROOT = REPO_ROOT / "data" / "raw"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
BOX_COLUMNS = (
    ["game_id", "team_id", "player_group", "player_id", "name", "starter", "decision"]
    + list(GOALIE_SUM_COLUMNS)
)
# NHL report field -> our column
COUNT_FIELDS = (
    ("gamesPlayed", "games_played"), ("gamesStarted", "games_started"), ("wins", "wins"),
    ("losses", "losses"), ("otLosses", "ot_losses"), ("shotsAgainst", "shots_against"),
    ("saves", "saves"), ("goalsAgainst", "goals_against"), ("timeOnIce", "toi_seconds"),
)


def shutout_variants(box_rows, regular_game_ids, shootout_games):
    """{variant number: Counter(player_id -> shutouts)} for the five definitions in the module docstring."""
    goalies_in_game = defaultdict(int)
    for row in box_rows:
        if row["player_group"] == "goalies" and row["game_id"] in regular_game_ids and (row["toi_seconds"] or 0) > 0:
            goalies_in_game[(row["game_id"], row["team_id"])] += 1
    variants = {number: Counter() for number in range(1, 6)}
    for row in box_rows:
        if row["player_group"] != "goalies" or row["game_id"] not in regular_game_ids:
            continue
        if (row["toi_seconds"] or 0) <= 0 or (row["goals_against"] or 0) != 0:
            continue
        player = row["player_id"]
        sole = goalies_in_game[(row["game_id"], row["team_id"])] == 1
        variants[1][player] += 1
        if row["decision"] == "W":
            variants[2][player] += 1
            if sole:
                variants[3][player] += 1
                if row["game_id"] not in shootout_games:
                    variants[4][player] += 1
        if sole and row["decision"] in ("W", "O"):
            variants[5][player] += 1
    return variants


def combine_by_player(rows):
    """Add the per-team rows of each goalie together."""
    combined = defaultdict(Counter)
    for row in rows:
        for column, value in row.items():
            if isinstance(value, int):
                combined[row["player_id"]][column] += value
    return combined


def main():
    parser = argparse.ArgumentParser(description="Check the goalie season totals.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    reference_path = RAW_ROOT / f"season={args.season}" / "reference" / "goalie_summary.json.gz"
    with gzip.open(reference_path, "rb") as handle:
        reference = {r["playerId"]: r for r in json.loads(handle.read())["data"]}
    print(f"Fields in the NHL report: {sorted(next(iter(reference.values())))}")

    staging = STAGING_ROOT / f"season={args.season}"
    games = pq.read_table(staging / "games.parquet", columns=["game_id", "game_type", "has_boxscore", "game_date"]).to_pylist()
    regular = {g["game_id"]: str(g["game_date"]) for g in games if g["game_type"] == REGULAR_SEASON and g["has_boxscore"]}
    events = pq.read_table(staging / "events.parquet", columns=["game_id", "period_type"]).to_pylist()
    shootout_games = {e["game_id"] for e in events if e["period_type"] == "SO"}
    box = pq.read_table(staging / "boxscore_players.parquet", columns=BOX_COLUMNS).to_pylist()

    rows = build_goalie_season_totals(box, set(regular), regular)
    ours = combine_by_player(rows)
    names = {r["player_id"]: r["name"] for r in rows}
    print(f"\nNHL goalies: {len(reference)}; ours: {len(ours)}; in the NHL report but not ours: "
          f"{len(set(reference) - set(ours))}; ours but not the NHL's: {len(set(ours) - set(reference))}")
    for player_id in sorted(set(reference) - set(ours))[:5]:
        print(f"  NHL only: {player_id} {reference[player_id].get('goalieFullName')} "
              f"GP {reference[player_id].get('gamesPlayed')}")
    for player_id in sorted(set(ours) - set(reference))[:5]:
        print(f"  ours only: {player_id} {names[player_id]} GP {ours[player_id]['games_played']}")

    compared = [p for p in reference if p in ours]
    print(f"\nPer goalie, ours against the NHL's, of {len(compared)} goalies:")
    for nhl_field, column in COUNT_FIELDS:
        if any(nhl_field not in reference[p] for p in compared):
            print(f"  {nhl_field:16s} the NHL report has no such field")
            continue
        diffs = [(ours[p][column] - reference[p][nhl_field], p) for p in compared]
        exact = sum(1 for d, _ in diffs if d == 0)
        within = sum(1 for d, _ in diffs if abs(d) <= 2)
        total_ours = sum(ours[p][column] for p in compared)
        total_nhl = sum(reference[p][nhl_field] for p in compared)
        worst = max(diffs, key=lambda d: abs(d[0]))
        print(f"  {nhl_field:16s} exact {exact:3d}, within 2 {within:3d}; total ours {total_ours}, NHL {total_nhl}; "
              f"largest gap {worst[0]:+d} (player {worst[1]})")

    print("\nSave percentage and goals-against average, worked out from our totals:")
    for nhl_field, label, digits in (("savePct", "save percentage", 3), ("goalsAgainstAverage", "goals-against average", 2)):
        if any(nhl_field not in reference[p] for p in compared):
            print(f"  {label}: the NHL report has no field {nhl_field}")
            continue
        close = 0
        for p in compared:
            saves, shots, toi, against = (ours[p][c] for c in ("saves", "shots_against", "toi_seconds", "goals_against"))
            value = (saves / shots if shots else None) if nhl_field == "savePct" else (against * 3600 / toi if toi else None)
            nhl_value = reference[p][nhl_field]
            close += value is not None and nhl_value is not None and abs(value - nhl_value) < 0.5 * 10 ** -digits
        print(f"  {label}: {close} of {len(compared)} match the NHL's to {digits} decimals")

    split_bad = sum(
        1 for r in rows
        if r["even_strength_shots_against"] + r["power_play_shots_against"] + r["shorthanded_shots_against"]
        != r["shots_against"]
        or r["even_strength_goals_against"] + r["power_play_goals_against"] + r["shorthanded_goals_against"]
        != r["goals_against"]
    )
    print(f"\nGoalie-team rows where the strength splits do not add up to the totals: {split_bad} of {len(rows)}")

    if all("shutouts" in reference[p] for p in compared):
        print("\nShutouts, goalies matching the NHL's count:")
        for number, counts in shutout_variants(box, set(regular), shootout_games).items():
            exact = sum(1 for p in compared if counts[p] == reference[p]["shutouts"])
            print(f"  definition {number}: {exact} of {len(compared)}; total ours {sum(counts[p] for p in compared)}, "
                  f"NHL {sum(reference[p]['shutouts'] for p in compared)}")
        best = shutout_variants(box, set(regular), shootout_games)[5]
        print("\nGoalies whose shutouts differ from the NHL's under definition 5:")
        for p in compared:
            if best[p] != reference[p]["shutouts"]:
                print(f"  {p} {reference[p].get('goalieFullName')}: ours {best[p]}, NHL {reference[p]['shutouts']}")
                for r in box:
                    if (r["player_id"] == p and r["player_group"] == "goalies" and r["game_id"] in regular
                            and (r["toi_seconds"] or 0) > 0 and not r["goals_against"]):
                        others = [x["toi_seconds"] for x in box if x["game_id"] == r["game_id"] and x["team_id"] == r["team_id"]
                                  and x["player_group"] == "goalies" and x["player_id"] != p and (x["toi_seconds"] or 0) > 0]
                        print(f"    game {r['game_id']} decision {r['decision']} toi {r['toi_seconds']} other goalies' toi {others}")
    else:
        print("\nThe NHL report has no 'shutouts' field.")


if __name__ == "__main__":
    main()