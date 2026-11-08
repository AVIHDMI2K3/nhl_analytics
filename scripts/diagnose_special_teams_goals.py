"""Check our power-play and shorthanded goals game by game against the boxscore's goalies.

Run from the repo root with the `nhl` conda environment active, after build_base_tables.py:

    python scripts/diagnose_special_teams_goals.py --season 2023

A goalie's `power_play_goals_against` are the power-play goals his team conceded (goals the OTHER
team scored on the power play) and his `shorthanded_goals_against` are the shorthanded goals the
other team scored. For every game with shift data this compares, per team, our goals for while on the
power play and while shorthanded (team_game_strength) with what the opponent's goalies were charged.
A goal into an empty net is charged to no goalie, so each line is shown twice: all of our goals, and
only the goals scored with a goalie in net. A third comparison gives each goal the strength of the NHL's
situation code on the goal event (shot_attempts: skaters and goalies of each side, a pulled goalie
not counted as a skater), to see whether the code or our shift-based strength agrees better with the
boxscore. It prints how many team-games agree, the totals, and the first games that do not (the
shift-based comparison with a goalie in net, then the code-based one).
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

from special_teams import code_strength  # noqa: E402

STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
# our strength -> the opponent goalie's boxscore column that should equal our goals for in it
BOX_COLUMN = {"pp": "power_play_goals_against", "sh": "shorthanded_goals_against"}


def code_goal_counts(goal_rows):
    """(all, with a goalie in net): Counters of goals by (strength, game_id, team_id) from the situation code."""
    everything, in_net = Counter(), Counter()
    for goal in goal_rows:
        key = (code_strength(goal), goal["game_id"], goal["team_id"])
        everything[key] += 1
        if goal["goalie_against"]:
            in_net[key] += 1
    return everything, in_net


def compare_by_game(team_rows, box_rows, code_goals=None):
    """[(situation, game_id, team_id, our goals, boxscore goals, our goals with a goalie in net,
    goals by the situation code, those with a goalie in net)] for every team-game with shift data.
    `code_goals` is the result of code_goal_counts (zeros when not given)."""
    code_all, code_net = code_goals or (Counter(), Counter())
    ours = Counter()
    in_net = Counter()
    teams = defaultdict(set)
    for row in team_rows:
        teams[row["game_id"]].add(row["team_id"])
        if row["strength"] in BOX_COLUMN:
            key = (row["strength"], row["game_id"], row["team_id"])
            ours[key] += row["for_goal"] or 0
            if row["goalies_against"]:
                in_net[key] += row["for_goal"] or 0
    charged = defaultdict(Counter)  # (game, goalie's team) -> boxscore column -> goals
    for row in box_rows:
        if row["player_group"] == "goalies":
            for column in BOX_COLUMN.values():
                charged[(row["game_id"], row["team_id"])][column] += row[column] or 0
    out = []
    for game_id, game_teams in sorted(teams.items()):
        for team_id in sorted(game_teams):
            opponents = game_teams - {team_id}
            if len(opponents) != 1:
                continue
            opponent = next(iter(opponents))
            for situation, column in BOX_COLUMN.items():
                key = (situation, game_id, team_id)
                out.append((situation, game_id, team_id, ours[key], charged[(game_id, opponent)][column], in_net[key],
                            code_all[key], code_net[key]))
    return out


def main():
    parser = argparse.ArgumentParser(description="Compare special-teams goals with the boxscore, game by game.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    team_rows = pq.read_table(
        METRICS_ROOT / f"season={args.season}" / "team_game_strength.parquet",
        columns=["game_id", "team_id", "strength", "for_goal", "goalies_against"],
    ).to_pylist()
    box_rows = pq.read_table(
        STAGING_ROOT / f"season={args.season}" / "boxscore_players.parquet",
        columns=["game_id", "team_id", "player_group"] + list(BOX_COLUMN.values()),
    ).to_pylist()
    goal_rows = [
        g for g in pq.read_table(
            METRICS_ROOT / f"season={args.season}" / "shot_attempts.parquet",
            columns=["game_id", "team_id", "attempt_type", "skaters_for", "skaters_against", "goalie_for", "goalie_against"],
        ).to_pylist() if g["attempt_type"] == "goal"
    ]
    rows = compare_by_game(team_rows, box_rows, code_goal_counts(goal_rows))
    for situation, label in (("pp", "Power-play goals"), ("sh", "Shorthanded goals")):
        part = [r for r in rows if r[0] == situation]
        print(f"\n{label}: {len(part)} team-games; total ours {sum(r[3] for r in part)} "
              f"(with a goalie in net {sum(r[5] for r in part)}), by situation code {sum(r[6] for r in part)} "
              f"(with a goalie in net {sum(r[7] for r in part)}), boxscore {sum(r[4] for r in part)}")
        for name, index in (("shift-based, all goals", 3), ("shift-based, goalie in net", 5),
                            ("situation code, all goals", 6), ("situation code, goalie in net", 7)):
            bad = [r for r in part if r[index] != r[4]]
            print(f"  {name}: {len(part) - len(bad)} team-games agree; higher in "
                  f"{sum(1 for r in bad if r[index] > r[4])}, lower in {sum(1 for r in bad if r[index] < r[4])}")
        for name, index in (("shift-based, goalie in net", 5), ("situation code, goalie in net", 7)):
            bad = [r for r in part if r[index] != r[4]]
            if bad:
                print(f"  first disagreements, {name}:")
            for r in bad[:10]:
                print(f"    game {r[1]} team {r[2]}: ours {r[index]}, boxscore {r[4]}")


if __name__ == "__main__":
    main()