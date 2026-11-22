"""Phase 3 check: which goal explains a plus/minus difference with the boxscore?

Run from the repo root with the `nhl` conda environment active:

    python scripts/find_pm_goals.py --season 2023

Read-only. For every game where our plus/minus differs from the boxscore, it tries
each goal of the game on its own. A goal "fits" when the differences equal that
goal's full effect (+1 for the scoring team's skaters on the ice, -1 for the
other team's), either as a goal we counted and the NHL did not (ours higher) or
the reverse. A fitting goal leaves no player unexplained.

If no goal fits, the script says so, lists the players who differ, and lists the
goals each of them was on the ice for, so the cause can be looked at by hand.
"""

import argparse
from collections import defaultdict
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"

VERDICTS = {1: "we counted it, the NHL did not", -1: "the NHL counted it, we did not"}


def table_path(root, season, table):
    return (root / f"season={season}" / f"{table}.parquet").as_posix()


def goal_effect(goal, home_team_id):
    """{player_id: +1 or -1} if this goal were counted in full."""
    if goal["owner"] == home_team_id:
        own, other = goal["home_skaters"], goal["away_skaters"]
    else:
        own, other = goal["away_skaters"], goal["home_skaters"]
    effect = {player: 1 for player in own}
    effect.update({player: -1 for player in other})
    return effect


def players_not_fitting(diff, effect, sign):
    """Players whose difference does not equal sign * the goal's effect."""
    players = set(diff) | set(effect)
    return sum(1 for p in players if diff.get(p, 0) != sign * effect.get(p, 0))


def best_fit(diff, goals, home_team_id):
    """The (goal, sign) that leaves the fewest players not fitting, with that count."""
    best = None
    for goal in goals:
        effect = goal_effect(goal, home_team_id)
        for sign in (1, -1):
            left = players_not_fitting(diff, effect, sign)
            if best is None or left < best[0]:
                best = (left, goal, sign)
    return best


def describe(goal, home_team_id):
    side = "home" if goal["owner"] == home_team_id else "away"
    return f"period {goal['period']}, second {goal['seconds']}, scored by {side}, code {goal['code']}"


def main():
    parser = argparse.ArgumentParser(description="Find goals behind plus/minus differences.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    con = duckdb.connect()
    events = table_path(INTERMEDIATE_ROOT, args.season, "event_on_ice")
    plus_minus = table_path(INTERMEDIATE_ROOT, args.season, "player_game_plus_minus")
    games = table_path(STAGING_ROOT, args.season, "games")
    box = table_path(STAGING_ROOT, args.season, "boxscore_players")

    diff_rows = con.execute(
        f"""
        select b.game_id, b.player_id, coalesce(p.plus_minus, 0) - b.plus_minus as diff
        from '{box}' as b
        left join '{plus_minus}' as p on p.game_id = b.game_id and p.player_id = b.player_id
        where b.player_group <> 'goalies' and b.plus_minus is not null
          and b.game_id in (select distinct game_id from '{events}')
        """
    ).fetchall()
    diffs = defaultdict(dict)
    for game_id, player_id, diff in diff_rows:
        if diff:
            diffs[game_id][player_id] = diff

    home = dict(con.execute(f"select game_id, home_team_id from '{games}'").fetchall())
    goal_rows = con.execute(
        f"""
        select game_id, period, game_seconds, event_owner_team_id, situation_code,
               home_skater_ids, away_skater_ids
        from '{events}' where event_type = 'goal'
        order by game_id, sort_order
        """
    ).fetchall()
    goals = defaultdict(list)
    for game_id, period, seconds, owner, code, home_ids, away_ids in goal_rows:
        goals[game_id].append(
            {
                "period": period,
                "seconds": seconds,
                "owner": owner,
                "code": code,
                "home_skaters": home_ids,
                "away_skaters": away_ids,
            }
        )

    print(f"{len(diffs)} games differ from the boxscore")
    for game_id in sorted(diffs):
        diff = diffs[game_id]
        print(f"\n{game_id}: {len(diff)} players differ")
        best = best_fit(diff, goals[game_id], home[game_id])
        if best is not None and best[0] == 0:
            _, goal, sign = best
            print(f"  one goal explains all of them: {describe(goal, home[game_id])}")
            print(f"  {VERDICTS[sign]}")
            continue
        print("  no single goal explains it. Players (ours minus boxscore) and the goals")
        print("  each was on the ice for:")
        for player_id, value in sorted(diff.items()):
            print(f"  player {player_id}: {value:+d}")
            for goal in goals[game_id]:
                if player_id in goal["home_skaters"] or player_id in goal["away_skaters"]:
                    print(f"    {describe(goal, home[game_id])}")


if __name__ == "__main__":
    main()
