"""Find the team-games where our shorthanded goal count differs from the NHL's, and show their goals.

Run from the repo root with the `nhl` conda environment active, after build_team_special_teams.py,
build_stints.py and ingest_reference.py:

    python scripts/diagnose_shorthanded_goals.py --season 2025

For every team-game where our sh_goals_for differs from the NHL's shGoalsFor (team_penaltykill_games), it
prints our and the NHL's count, then every goal of the game: period and clock, scoring team, the NHL
situation code, our real skaters from the stint, and the penalties called in the ten minutes before.
That shows which goal the NHL counts as shorthanded and we do not.
"""

import argparse
import gzip
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from inspect_goal_strength import our_view, recent_penalties, stint_at  # noqa: E402

RAW_ROOT = REPO_ROOT / "data" / "raw"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"


def disagreeing(ours, nhl):
    """[(game_id, team_id, ours, nhl)] where the counts differ; ours and nhl are {(game_id, team_id): count}."""
    return [(g, t, ours.get((g, t), 0), n) for (g, t), n in sorted(nhl.items()) if ours.get((g, t), 0) != n]


def main():
    parser = argparse.ArgumentParser(description="Show the games where shorthanded goals disagree with the NHL.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    staging = STAGING_ROOT / f"season={args.season}"
    metrics = METRICS_ROOT / f"season={args.season}"

    with gzip.open(RAW_ROOT / f"season={args.season}" / "reference" / "team_penaltykill_games.json.gz", "rb") as handle:
        nhl = {(r["gameId"], r["teamId"]): r["shGoalsFor"] for r in json.loads(handle.read())["data"]}
    ours = {(r["game_id"], r["team_id"]): r["sh_goals_for"]
            for r in pq.read_table(metrics / "team_game_special_teams.parquet").to_pylist()}
    differences = disagreeing(ours, nhl)
    print(f"Season {args.season}: {len(differences)} team-games where shorthanded goals for differ from the NHL's")
    wanted = {g for g, _, _, _ in differences}
    games = {g["game_id"]: g for g in pq.read_table(
        staging / "games.parquet", columns=["game_id", "home_team_id", "home_team", "away_team_id", "away_team"]
    ).to_pylist() if g["game_id"] in wanted}
    events = [e for e in pq.read_table(staging / "events.parquet", columns=[
        "game_id", "sort_order", "period", "period_type", "seconds_in_period", "game_seconds", "event_type",
        "event_owner_team_id", "situation_code", "penalty_desc_key", "penalty_minutes",
    ]).to_pylist() if e["game_id"] in wanted]
    stints = [s for s in pq.read_table(metrics / "stints.parquet").to_pylist() if s["game_id"] in wanted]

    for game_id, team_id, mine, theirs in differences:
        game = games[game_id]
        name = game["home_team"] if team_id == game["home_team_id"] else game["away_team"]
        print(f"\ngame {game_id}: {game['away_team']} at {game['home_team']}; {name} shorthanded goals ours {mine}, NHL {theirs}")
        game_events = sorted((e for e in events if e["game_id"] == game_id), key=lambda e: e["sort_order"])
        game_stints = [s for s in stints if s["game_id"] == game_id]
        for goal in (e for e in game_events if e["event_type"] == "goal" and e["period_type"] != "SO"):
            home = goal["event_owner_team_id"] == game["home_team_id"]
            scorer = game["home_team"] if home else game["away_team"]
            real_mine, real_theirs, strength = our_view(stint_at(game_stints, goal["game_seconds"]), home)
            minute, second = divmod(goal["seconds_in_period"], 60)
            print(f"  P{goal['period']} {minute:2d}:{second:02d} {scorer}  code {goal['situation_code']}  "
                  f"stint skaters {real_mine} v {real_theirs} ({strength})")
            for p in recent_penalties(game_events, goal["game_seconds"]):
                owner = game["home_team"] if p["event_owner_team_id"] == game["home_team_id"] else game["away_team"]
                p_min, p_sec = divmod(p["game_seconds"] - 1200 * (p["period"] - 1), 60)
                print(f"      penalty P{p['period']} {p_min:2d}:{p_sec:02d} {owner} {p['penalty_desc_key']} {p['penalty_minutes']} min")


if __name__ == "__main__":
    main()