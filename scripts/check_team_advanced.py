"""Check the advanced on-ice team table (Phase 4.8).

Run from the repo root with the `nhl` conda environment active, after build_team_advanced.py:

    python scripts/check_team_advanced.py --season 2025

1. Over all teams, attempts for equal attempts against in 'all' and in 5v5 (every attempt is for
   one team and against the other, in both situations).
2. The team table agrees with the player table: five times the 5v5 team attempts equals the
   players' summed on-ice attempts (checked in check_player_advanced.py; repeated here).
3. Each team's time in 'all' per game, which should be a regulation game plus any overtime.
4. Goals for and against by team, to compare with the standings by eye.
"""

import argparse
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
METRICS_ROOT = REPO_ROOT / "data" / "metrics"


def main():
    parser = argparse.ArgumentParser(description="Check the advanced on-ice team table.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    metrics = METRICS_ROOT / f"season={args.season}"

    teams = pq.read_table(metrics / "team_season_advanced.parquet").to_pylist()
    players = pq.read_table(metrics / "player_season_advanced.parquet", columns=["kind", "situation", "cf"]).to_pylist()
    print(f"Season {args.season}: {len(teams)} rows, {len({r['team'] for r in teams})} teams")

    print("\n1. Attempts for vs against over all teams")
    for situation in ("all", "5v5"):
        rows = [r for r in teams if r["situation"] == situation]
        cf, ca = sum(r["cf"] for r in rows), sum(r["ca"] for r in rows)
        print(
            f"  {situation:4s} for {cf}, against {ca}: {'equal' if cf == ca else 'NOT equal, difference ' + str(cf - ca)}"
        )

    five_team = sum(r["cf"] for r in teams if r["situation"] == "5v5")
    five_players = sum(r["cf"] for r in players if r["kind"] == "team" and r["situation"] == "5v5")
    print(
        f"\n2. 5 x team Corsi for {5 * five_team} vs players' on-ice Corsi for {five_players}: "
        f"{'equal' if 5 * five_team == five_players else 'NOT equal'}"
    )

    print("\n3. Time per game in 'all' (seconds; regulation is 3600)")
    per_game = sorted((r["seconds"] / r["games_included"], r["team"]) for r in teams if r["situation"] == "all")
    print(f"  lowest {per_game[0][0]:.0f} ({per_game[0][1]}), highest {per_game[-1][0]:.0f} ({per_game[-1][1]})")

    print(
        "\n4. Goals for and against, all situations (attempts that were goals; shootouts and penalty shots are not in them)"
    )
    for r in sorted((r for r in teams if r["situation"] == "all"), key=lambda r: r["team"]):
        print(f"  {r['team']:4s} GP {r['games_played']:3d}/{r['games_included']:3d}  GF {r['gf']:3d}  GA {r['ga']:3d}")


if __name__ == "__main__":
    main()
