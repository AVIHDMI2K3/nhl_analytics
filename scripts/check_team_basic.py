"""Check the team season basic table (Phase 4.9).

Run from the repo root with the `nhl` conda environment active, after build_team_basic.py:

    python scripts/check_team_basic.py --season 2025

1. How games ended (last_period_type), since the record depends on it.
2. Totals that must balance over all teams: wins against losses plus overtime losses, goals for
   against goals against, points against 2 x wins + overtime losses, shots for against shots against.
3. Shots against from the opponent's skaters against the goalies' own shots-against in the boxscore.
4. Our goal attempts (team_season_advanced, all situations) against the final scores: the final
   scores include a shootout-winning goal and penalty-shot goals, which our attempts leave out, and
   our attempts miss the 57 games without shifts in 2024-25.
5. Power-play goals scored by skaters against power-play goals allowed by goalies, over all teams.
"""

import argparse
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"


def main():
    parser = argparse.ArgumentParser(description="Check the team season basic table.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    staging = STAGING_ROOT / f"season={args.season}"
    metrics = METRICS_ROOT / f"season={args.season}"

    teams = pq.read_table(metrics / "team_season_basic.parquet").to_pylist()
    games = pq.read_table(
        staging / "games.parquet", columns=["game_type", "has_boxscore", "last_period_type", "home_score", "away_score"]
    ).to_pylist()
    regular = [g for g in games if g["game_type"] == 2 and g["has_boxscore"]]
    print(f"Season {args.season}: {len(teams)} teams, {len(regular)} regular-season games with a boxscore")

    print("\n1. How games ended: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(str(g["last_period_type"]) for g in regular).items())))

    total = lambda column: sum(t[column] for t in teams)  # noqa: E731
    print("\n2. Balances over all teams")
    print(f"  wins {total('wins')} vs losses + overtime losses {total('losses') + total('ot_losses')}")
    print(f"  goals for {total('goals_for')} vs goals against {total('goals_against')}")
    print(f"  points {total('points')} vs 2 x wins + overtime losses {2 * total('wins') + total('ot_losses')}")
    print(f"  shots for {total('shots_for')} vs shots against {total('shots_against')}")
    print(f"  games played (sum) {total('games_played')} vs 2 x games {2 * len(regular)}")

    box = pq.read_table(staging / "boxscore_players.parquet", columns=["game_id", "team_id", "player_group", "shots_against"]).to_pylist()
    goalie_shots = Counter()
    for row in box:
        if row["player_group"] == "goalies":
            goalie_shots[row["team_id"]] += row["shots_against"] or 0
    differences = {t["team"]: goalie_shots[t["team_id"]] - t["shots_against"] for t in teams if goalie_shots[t["team_id"]] != t["shots_against"]}
    print(f"\n3. Goalies' shots against vs the opponent's skater shots: {len(teams) - len(differences)} of {len(teams)} teams equal")
    for team, diff in sorted(differences.items(), key=lambda item: -abs(item[1]))[:5]:
        print(f"  {team}: goalies minus opponent skaters {diff:+d}")

    advanced = pq.read_table(metrics / "team_season_advanced.parquet", columns=["team_id", "situation", "gf"]).to_pylist()
    attempts_goals = sum(r["gf"] for r in advanced if r["situation"] == "all")
    shootout_games = sum(1 for g in regular if g["last_period_type"] == "SO")
    print("\n4. Goals")
    print(f"  final scores {total('goals_for')}, our goal attempts {attempts_goals}, difference {total('goals_for') - attempts_goals}")
    print(f"  shootout games {shootout_games} (each adds one goal to the final score)")

    print(f"\n5. Power-play goals: scored {total('pp_goals_for')}, allowed {total('pp_goals_against')}")


if __name__ == "__main__":
    main()