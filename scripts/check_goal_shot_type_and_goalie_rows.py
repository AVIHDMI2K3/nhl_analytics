"""Two checks that follow from scripts/diagnose_boxscore_vs_pbp.py.

Run from the repo root with the `nhl` conda environment active:

    python scripts/check_goal_shot_type_and_goalie_rows.py --season 2025

1. Goals without a shot type. In the diagnosis every skater-game and goalie-game where the boxscore
   is one shot below the play-by-play had a goal with no shot type, and no agreeing game did.
   This tests that on every goal: how many goals have no shot type (with a goalie named, empty
   net), what the skater-games look like by (has such a goal, events minus boxscore shots), and
   whether the scorer's boxscore shows more goals than shots on goal (a goal that is not a shot).
2. Goalie rows dropped by shift cleaning. The 13 shots with no goalie on the ice all fell inside a raw
   goalie row that cleaning dropped. A candidate rule: a shot at a second where no kept goalie row of
   the defending team covers it, but a dropped goalie row does, is credited to that goalie. Before
   building it, this tests the rule on every shot that names a goalie (it should fix the 13) and on
   every empty-net shot (it must not fill any, or it would hide real empty nets).
Shootout events are left out.
"""

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"
SHOT_TYPES = ("goal", "shot-on-goal")
EVENT_COLUMNS = [
    "game_id", "event_type", "period_type", "game_seconds", "event_owner_team_id",
    "shooting_player_id", "scoring_player_id", "goalie_in_net_id", "shot_type",
]


def shooter_of(event):
    return event["scoring_player_id"] if event["event_type"] == "goal" else event["shooting_player_id"]


def covers(row, second, end_inclusive=False):
    """True if the row's shift covers the second: start included, end included only for a goal (as in the stints)."""
    return row["start"] <= second and (second <= row["end"] if end_inclusive else second < row["end"])


def fill_status(kept, dropped, second, end_inclusive=False):
    """'kept' if a kept row covers the second, 'fillable' if only a dropped row does, else 'uncovered'."""
    if any(covers(row, second, end_inclusive) for row in kept):
        return "kept"
    if any(covers(row, second, end_inclusive) for row in dropped):
        return "fillable"
    return "uncovered"


def edge_distance(rows, second):
    """Seconds from `second` to the nearest start or end of any row (None if there are no rows)."""
    distances = [min(abs(second - row["start"]), abs(second - row["end"])) for row in rows]
    return min(distances) if distances else None


def tally_skater_games(shots, box_sog):
    """Counter of (has a goal with no shot type, events minus boxscore shots) over skater-games of one game.

    `shots` are the game's shot and goal events, `box_sog` maps skater id -> boxscore shots on goal.
    Events by someone who is not a skater in the boxscore (a goalie shooting) are left out.
    """
    events = Counter()
    no_type = Counter()
    for event in shots:
        shooter = shooter_of(event)
        if shooter not in box_sog:
            continue
        events[shooter] += 1
        if event["event_type"] == "goal" and event["shot_type"] is None:
            no_type[shooter] += 1
    return Counter((no_type[player] > 0, events[player] - box_sog[player]) for player in box_sog)


def report_goal_shot_type(events_by_game, box_by_game):
    total = with_goalie = empty_net = 0
    cross = Counter()
    goals_above_sog = Counter()
    for game_id, events in events_by_game.items():
        shots = [e for e in events if e["event_type"] in SHOT_TYPES and e["period_type"] != "SO"]
        for event in shots:
            if event["event_type"] == "goal" and event["shot_type"] is None:
                total += 1
                if event["goalie_in_net_id"] is None:
                    empty_net += 1
                else:
                    with_goalie += 1
        skaters = {r["player_id"]: r for r in box_by_game[game_id] if r["player_group"] != "goalies"}
        cross.update(tally_skater_games(shots, {pid: r["sog"] for pid, r in skaters.items()}))
        if box_by_game and any("goals" in r for r in skaters.values()):
            for event in shots:
                if event["event_type"] == "goal" and event["shot_type"] is None and event["scoring_player_id"] in skaters:
                    row = skaters[event["scoring_player_id"]]
                    goals_above_sog[row["goals"] > row["sog"]] += 1
    print("1. Goals without a shot type")
    print(f"  goals with no shot type: {total} (a goalie named: {with_goalie}, empty net: {empty_net})")
    print("  skater-games by (has a goal with no shot type, events minus boxscore shots):")
    for (has_goal, difference), n in sorted(cross.items()):
        print(f"    no-type goal: {str(has_goal):5s}  difference {difference:+d}: {n}")
    if goals_above_sog:
        print(f"  scorers of those goals whose boxscore goals exceed their shots on goal: "
              f"{goals_above_sog[True]} of {sum(goals_above_sog.values())}")
    else:
        print("  (the boxscore table has no 'goals' column, so goals vs shots on goal was not checked)")


def report_goalie_rows(games, events_by_game, goalies_of_team, raw_by_game, kept_keys):
    statuses = Counter()
    kept_distance = Counter()
    filled_rows = Counter()
    for game_id, game in games.items():
        rows = defaultdict(lambda: {"kept": [], "dropped": []})
        for r in raw_by_game.get(game_id, []):
            if r["player_id"] not in goalies_of_team[game_id]:
                continue
            if r["start_game_seconds"] is None or r["end_game_seconds"] is None:
                continue
            row = {"start": r["start_game_seconds"], "end": r["end_game_seconds"]}
            key = (game_id, r["player_id"], r["start_game_seconds"], r["end_game_seconds"])
            rows[goalies_of_team[game_id][r["player_id"]]]["kept" if key in kept_keys else "dropped"].append(row)
        for event in events_by_game[game_id]:
            if event["event_type"] not in SHOT_TYPES or event["period_type"] == "SO":
                continue
            owner = event["event_owner_team_id"]
            defending = game["away_team_id"] if owner == game["home_team_id"] else game["home_team_id"]
            kind = "names a goalie" if event["goalie_in_net_id"] is not None else "empty net"
            is_goal = event["event_type"] == "goal"
            status = fill_status(rows[defending]["kept"], rows[defending]["dropped"], event["game_seconds"], is_goal)
            statuses[(kind, status)] += 1
            if kind == "empty net" and status == "kept":
                near = edge_distance([r for r in rows[defending]["kept"] if covers(r, event["game_seconds"], is_goal)], event["game_seconds"])
                kept_distance[min(near, 10)] += 1
            if status == "fillable":
                covering = [r for r in rows[defending]["dropped"] if covers(r, event["game_seconds"])]
                filled_rows[(kind, covering[0]["start"], covering[0]["end"])] += 1
    print("\n2. Goalie rows dropped by cleaning: would 'fill from a dropped row' be safe?")
    for kind in ("names a goalie", "empty net"):
        print(f"  shots where the play-by-play {kind}: "
              f"covered by a kept goalie row {statuses[(kind, 'kept')]}, "
              f"only by a dropped row {statuses[(kind, 'fillable')]}, "
              f"by no row {statuses[(kind, 'uncovered')]}")
    print("  empty-net shots that a kept goalie row still covers: seconds to that row's nearest edge (10 = 10 or more):")
    print("   ", dict(sorted(kept_distance.items())))
    print("  the dropped rows that would be used: (kind, start, end): shots")
    for key, n in sorted(filled_rows.items()):
        print(f"    {key}: {n}")


def main():
    parser = argparse.ArgumentParser(description="Goals without a shot type; goalie rows dropped by cleaning.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    staging = STAGING_ROOT / f"season={args.season}"

    games = {g["game_id"]: g for g in pq.read_table(
        staging / "games.parquet", columns=["game_id", "game_type", "has_boxscore", "home_team_id", "away_team_id"]
    ).to_pylist() if g["game_type"] == 2 and g["has_boxscore"]}
    events_by_game, box_by_game, goalies_of_team = defaultdict(list), defaultdict(list), defaultdict(dict)
    for row in pq.read_table(staging / "events.parquet", columns=EVENT_COLUMNS).to_pylist():
        if row["game_id"] in games:
            events_by_game[row["game_id"]].append(row)
    box_columns = ["game_id", "team_id", "player_group", "player_id", "sog"]
    if "goals" in pq.read_schema(staging / "boxscore_players.parquet").names:
        box_columns.append("goals")
    for row in pq.read_table(staging / "boxscore_players.parquet", columns=box_columns).to_pylist():
        if row["game_id"] in games:
            box_by_game[row["game_id"]].append(row)
            if row["player_group"] == "goalies":
                goalies_of_team[row["game_id"]][row["player_id"]] = row["team_id"]
    raw_by_game = defaultdict(list)
    for row in pq.read_table(
        staging / "shifts.parquet", columns=["game_id", "player_id", "start_game_seconds", "end_game_seconds"]
    ).to_pylist():
        if row["game_id"] in games and row["player_id"] in goalies_of_team[row["game_id"]]:
            raw_by_game[row["game_id"]].append(row)
    kept_keys = {(r["game_id"], r["player_id"], r["start_game_seconds"], r["end_game_seconds"]) for r in pq.read_table(
        INTERMEDIATE_ROOT / f"season={args.season}" / "shifts_clean.parquet",
        columns=["game_id", "player_id", "start_game_seconds", "end_game_seconds"],
    ).to_pylist()}

    print(f"Season {args.season}: {len(games)} games\n")
    report_goal_shot_type(events_by_game, box_by_game)
    report_goalie_rows(games, events_by_game, goalies_of_team, raw_by_game, kept_keys)


if __name__ == "__main__":
    main()