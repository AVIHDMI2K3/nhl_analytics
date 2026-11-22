"""Look at the goals of a few games: what strength we gave each goal, and which penalties were running.

Run from the repo root with the `nhl` conda environment active, after build_stints.py. Use the game
ids that scripts/diagnose_special_teams_goals.py lists as disagreeing with the boxscore:

    python scripts/inspect_goal_strength.py --season 2023 --games 2023020069 2023020307

For every goal of each game it prints the period and clock, the scoring team, the NHL's situation code,
our real skaters for the scoring side and its opponent and the strength we gave the scoring team (from
the stint that covers the goal's second, end-inclusive like the boxscore rule), and the penalties
called in the ten minutes before the goal, so the strength can be checked by hand against the rules.
"""

import argparse
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
PENALTY_WINDOW_SECONDS = 600


def stint_at(stints, second):
    """The stint covering `second` for a goal: start < second <= end (a goal belongs to the stint that
    ends on its second). None if there is none."""
    for stint in stints:
        if stint["start_game_seconds"] < second <= stint["end_game_seconds"]:
            return stint
    return None


def our_view(stint, scoring_is_home):
    """(scoring side's real skaters, opponent's real skaters, scoring side's strength) from a stint."""
    if stint is None:
        return None, None, None
    mine, theirs = ("home", "away") if scoring_is_home else ("away", "home")
    return stint[f"{mine}_real_skaters"], stint[f"{theirs}_real_skaters"], stint[f"{mine}_strength"]


def recent_penalties(events, second, window=PENALTY_WINDOW_SECONDS):
    """Penalty events in the `window` seconds up to `second`, oldest first."""
    return [e for e in events if e["event_type"] == "penalty" and second - window <= e["game_seconds"] <= second]


def main():
    parser = argparse.ArgumentParser(description="Show the strength given to each goal of some games.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--games", type=int, nargs="+", required=True)
    args = parser.parse_args()
    wanted = set(args.games)
    staging = STAGING_ROOT / f"season={args.season}"
    metrics = METRICS_ROOT / f"season={args.season}"

    games = {
        g["game_id"]: g
        for g in pq.read_table(
            staging / "games.parquet", columns=["game_id", "home_team_id", "home_team", "away_team_id", "away_team"]
        ).to_pylist()
        if g["game_id"] in wanted
    }
    events = [
        e
        for e in pq.read_table(
            staging / "events.parquet",
            columns=[
                "game_id",
                "event_id",
                "sort_order",
                "period",
                "period_type",
                "seconds_in_period",
                "game_seconds",
                "event_type",
                "event_owner_team_id",
                "situation_code",
                "penalty_desc_key",
                "penalty_minutes",
                "scoring_player_id",
            ],
        ).to_pylist()
        if e["game_id"] in wanted
    ]
    stints = [s for s in pq.read_table(metrics / "stints.parquet").to_pylist() if s["game_id"] in wanted]

    for game_id in args.games:
        game = games.get(game_id)
        if game is None:
            print(f"\ngame {game_id}: not found")
            continue
        print(f"\ngame {game_id}: {game['away_team']} at {game['home_team']}")
        game_events = sorted((e for e in events if e["game_id"] == game_id), key=lambda e: e["sort_order"])
        game_stints = [s for s in stints if s["game_id"] == game_id]
        for goal in (e for e in game_events if e["event_type"] == "goal" and e["period_type"] != "SO"):
            scoring_is_home = goal["event_owner_team_id"] == game["home_team_id"]
            team = game["home_team"] if scoring_is_home else game["away_team"]
            mine, theirs, strength = our_view(stint_at(game_stints, goal["game_seconds"]), scoring_is_home)
            minute, second = divmod(goal["seconds_in_period"], 60)
            print(
                f"  P{goal['period']} {minute:2d}:{second:02d} {team}  situation code {goal['situation_code']}  "
                f"our real skaters {mine} v {theirs}, strength for {team}: {strength}"
            )
            for penalty in recent_penalties(game_events, goal["game_seconds"]):
                owner = (
                    game["home_team"] if penalty["event_owner_team_id"] == game["home_team_id"] else game["away_team"]
                )
                p_minute, p_second = divmod(penalty["game_seconds"] - 1200 * (penalty["period"] - 1), 60)
                print(
                    f"      penalty P{penalty['period']} {p_minute:2d}:{p_second:02d} {owner} "
                    f"{penalty['penalty_desc_key']} {penalty['penalty_minutes']} min"
                )


if __name__ == "__main__":
    main()
