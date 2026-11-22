"""Find what causes the gap between skaters' shots and goalies' shots against.

Run from the repo root with the `nhl` conda environment active (2025 has all games with shifts):

    python scripts/diagnose_shots_against_gap.py --season 2025

For a team defending in a game, the boxscore gives two numbers that should agree except for shots
on an empty net: the opponent skaters' shots on goal (S) and the team's goalies' shots against (G).
Three sources are compared, shot by shot and game by game:

  boxscore   S and G
  events     the NHL play-by-play. Every goal and shot-on-goal names the goalie in net
             (goalie_in_net_id), or none when the net was empty.
  shifts     our stints: whether the defending team had a goalie on the ice at that second.

Tests:
  1. S against the number of shot and goal events by the opponent; G against the events that name
     one of the team's goalies; S - G against the events with no goalie named.
  2. Shift timing: events where the play-by-play and our shifts disagree about an empty net,
     with the distance in seconds to the nearest moment our shifts change the goalie. If shift
     timing is the cause they sit within about 2 seconds of a change.
  3. The team-games where S - G is still not the play-by-play's empty-net count, with what they have
     in common (overtime, a penalty shot).
  4. Each goalie's boxscore shots against against the events that name him.
Shootout events are left out. Penalty shots are included and counted.
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

from stints import StintIndex  # noqa: E402

STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
SHOT_TYPES = ("goal", "shot-on-goal")
PENALTY_SHOT_CODES = ("1010", "0101")
EVENT_COLUMNS = [
    "game_id",
    "event_id",
    "event_type",
    "period_type",
    "game_seconds",
    "event_owner_team_id",
    "goalie_in_net_id",
    "situation_code",
]
BOX_COLUMNS = ["game_id", "team_id", "player_group", "player_id", "sog", "shots_against"]
RECORD_KEYS = (
    "events",
    "overtime_events",
    "penalty_shots",
    "events_empty",
    "events_goalie",
    "stints_empty",
    "outside_stints",
    "box_goalie_shots",
    "box_skater_shots",
)
BUCKETS = (("0 s", 0), ("1 s", 1), ("2 s", 2), ("3-5 s", 5), ("6-10 s", 10), ("more", None))


def bucket(distance):
    for name, limit in BUCKETS:
        if limit is None or distance <= limit:
            return name


def goalie_changes(stints):
    """{side: sorted times at which the side's goalie presence changes within a period}."""
    changes = {"home": [], "away": []}
    for side in changes:
        previous = None
        for row in stints:
            present = bool(row[f"{side}_goalie_ids"])
            starts_period = previous is None or previous["period"] != row["period"]
            if not starts_period and bool(previous[f"{side}_goalie_ids"]) != present:
                changes[side].append(row["start_game_seconds"])
            previous = row
    return changes


def analyze_game(game, events, stints, box_rows):
    """Per defending team: counts from the three sources, plus the events where events and shifts disagree.

    Returns (team_records, mismatches, goalie_records). A mismatch is a dict with kind and the
    distance in seconds to the nearest change of the defending goalie in our shifts (None if no stints).
    """
    teams = {"home": game["home_team_id"], "away": game["away_team_id"]}
    side_of = {team: side for side, team in teams.items()}
    records = {team: Counter() for team in teams.values()}
    goalie_events = Counter()
    mismatches = []
    index = StintIndex(stints) if stints else None
    changes = goalie_changes(stints) if stints else {"home": [], "away": []}

    for event in events:
        if event["event_type"] not in SHOT_TYPES or event["period_type"] == "SO":
            continue
        shooter = event["event_owner_team_id"]
        if shooter not in side_of:
            continue
        defender = teams["away" if side_of[shooter] == "home" else "home"]
        defending_side = side_of[defender]
        record = records[defender]
        record["events"] += 1
        if event["period_type"] == "OT":
            record["overtime_events"] += 1
        if event["situation_code"] in PENALTY_SHOT_CODES:
            record["penalty_shots"] += 1
        goalie = event["goalie_in_net_id"]
        if goalie is None:
            record["events_empty"] += 1
        else:
            record["events_goalie"] += 1
            goalie_events[goalie] += 1
        if index is not None:
            stint = index.at(event["game_seconds"], end_inclusive=event["event_type"] == "goal")
            if stint is not None:
                stint_empty = not stint[f"{defending_side}_goalie_ids"]
                record["stints_empty"] += stint_empty
                if stint_empty != (goalie is None):
                    near = changes[defending_side]
                    distance = min((abs(event["game_seconds"] - t) for t in near), default=None)
                    mismatches.append(
                        {
                            "game_id": game["game_id"],
                            "team_id": defender,
                            "game_seconds": event["game_seconds"],
                            "kind": "play-by-play empty, shifts show a goalie"
                            if goalie is None
                            else "play-by-play has a goalie, shifts show none",
                            "distance": distance,
                        }
                    )
            else:
                record["outside_stints"] += 1

    goalie_records = []
    for row in box_rows:
        side = side_of.get(row["team_id"])
        if side is None:
            continue
        opponent = teams["away" if side == "home" else "home"]
        record = records[row["team_id"]]
        if row["player_group"] == "goalies":
            record["box_goalie_shots"] += row["shots_against"] or 0
            goalie_records.append(
                {
                    "game_id": game["game_id"],
                    "player_id": row["player_id"],
                    "team_id": row["team_id"],
                    "box": row["shots_against"] or 0,
                    "events": goalie_events[row["player_id"]],
                }
            )
        else:
            records[opponent]["box_skater_shots"] += row["sog"] or 0
    return records, mismatches, goalie_records


def team_record(game_id, team_id, has_shifts, record):
    """A plain dict with every count present (a Counter leaves out the ones that are zero)."""
    return {
        "game_id": game_id,
        "team_id": team_id,
        "has_shifts": has_shifts,
        **{key: record[key] for key in RECORD_KEYS},
    }


def percent(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def main():
    parser = argparse.ArgumentParser(description="Find what causes the shots-against gap.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    staging = STAGING_ROOT / f"season={args.season}"
    metrics = METRICS_ROOT / f"season={args.season}"

    games = {
        g["game_id"]: g
        for g in pq.read_table(
            staging / "games.parquet", columns=["game_id", "game_type", "has_boxscore", "home_team_id", "away_team_id"]
        ).to_pylist()
        if g["game_type"] == 2 and g["has_boxscore"]
    }
    by_game = {name: defaultdict(list) for name in ("events", "stints", "box")}
    for row in pq.read_table(staging / "events.parquet", columns=EVENT_COLUMNS).to_pylist():
        by_game["events"][row["game_id"]].append(row)
    for row in pq.read_table(metrics / "stints.parquet").to_pylist():
        by_game["stints"][row["game_id"]].append(row)
    for row in pq.read_table(staging / "boxscore_players.parquet", columns=BOX_COLUMNS).to_pylist():
        by_game["box"][row["game_id"]].append(row)

    team_games, all_mismatches, goalie_games = [], [], []
    for game_id, game in games.items():
        stints = sorted(by_game["stints"].get(game_id, []), key=lambda r: r["start_game_seconds"])
        records, mismatches, goalie_records = analyze_game(
            game, by_game["events"][game_id], stints, by_game["box"][game_id]
        )
        for team_id, record in records.items():
            team_games.append(team_record(game_id, team_id, bool(stints), record))
        all_mismatches.extend(mismatches)
        goalie_games.extend(goalie_records)
    shifted = [t for t in team_games if t["has_shifts"]]
    print(f"Season {args.season}: {len(team_games)} team-games ({len(shifted)} with shift data)")

    print("\n1. Boxscore against play-by-play, team-games")
    checks = (
        (
            "opponent skaters' shots (S) = shot and goal events by the opponent",
            lambda t: t["box_skater_shots"] == t["events"],
        ),
        (
            "goalies' shots against (G) = events that name one of the team's goalies",
            lambda t: t["box_goalie_shots"] == t["events_goalie"],
        ),
        (
            "S - G = events with no goalie named",
            lambda t: t["box_skater_shots"] - t["box_goalie_shots"] == t["events_empty"],
        ),
    )
    for label, test in checks:
        ok = sum(1 for t in team_games if test(t))
        print(f"  {label}: {ok} of {len(team_games)} ({percent(ok, len(team_games))})")
    print(
        f"  totals: S {sum(t['box_skater_shots'] for t in team_games)}, G {sum(t['box_goalie_shots'] for t in team_games)}, "
        f"events {sum(t['events'] for t in team_games)}, events with a goalie {sum(t['events_goalie'] for t in team_games)}, "
        f"events with none {sum(t['events_empty'] for t in team_games)}"
    )

    print("\n2. Shift timing: play-by-play and our shifts disagree about an empty net (games with shifts)")
    print(
        f"  empty-net events in games with shifts: play-by-play {sum(t['events_empty'] for t in shifted)}, "
        f"our shifts {sum(t['stints_empty'] for t in shifted)}; events outside our stints {sum(t['outside_stints'] for t in shifted)}"
    )
    for kind in sorted({m["kind"] for m in all_mismatches}):
        mine = [m for m in all_mismatches if m["kind"] == kind]
        histogram = Counter(bucket(m["distance"]) if m["distance"] is not None else "no change in game" for m in mine)
        print(
            f"  {kind}: {len(mine)} events; seconds to the nearest goalie change in our shifts: "
            + ", ".join(
                f"{name} {histogram[name]}" for name, _ in BUCKETS + (("no change in game", 0),) if histogram[name]
            )
        )
    if not all_mismatches:
        print("  no disagreements")

    print("\n3. Team-games where S - G is not the play-by-play's empty-net count")
    off = [t for t in team_games if t["box_skater_shots"] - t["box_goalie_shots"] != t["events_empty"]]
    print(
        f"  {len(off)} of {len(team_games)}; with overtime shots: {sum(1 for t in off if t['overtime_events'])}, "
        f"with a penalty shot: {sum(1 for t in off if t['penalty_shots'])}"
    )
    base = [t for t in team_games if t not in off]
    print(
        f"  for comparison, the others: overtime {percent(sum(1 for t in base if t['overtime_events']), len(base))}, "
        f"penalty shot {percent(sum(1 for t in base if t['penalty_shots']), len(base))}; "
        f"the off ones: overtime {percent(sum(1 for t in off if t['overtime_events']), len(off))}, "
        f"penalty shot {percent(sum(1 for t in off if t['penalty_shots']), len(off))}"
    )
    for t in sorted(off, key=lambda t: -abs(t["box_skater_shots"] - t["box_goalie_shots"] - t["events_empty"]))[:10]:
        print(
            f"    game {t['game_id']} team {t['team_id']}: S {t['box_skater_shots']} G {t['box_goalie_shots']} "
            f"S-G {t['box_skater_shots'] - t['box_goalie_shots']}, events {t['events']} (goalie {t['events_goalie']}, none {t['events_empty']}), "
            f"our shifts none {t['stints_empty']}, penalty shots {t['penalty_shots']}"
        )

    print("\n4. Each goalie's boxscore shots against vs events that name him")
    equal = sum(1 for g in goalie_games if g["box"] == g["events"])
    print(f"  equal for {equal} of {len(goalie_games)} goalie-games ({percent(equal, len(goalie_games))})")
    for g in sorted((g for g in goalie_games if g["box"] != g["events"]), key=lambda g: -abs(g["box"] - g["events"]))[
        :8
    ]:
        print(f"    game {g['game_id']} goalie {g['player_id']}: boxscore {g['box']}, events {g['events']}")


if __name__ == "__main__":
    main()
