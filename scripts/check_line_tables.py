"""Check the line and pair tables against the players' own 5v5 numbers (Phase 6).

For every skater and team, adds up the 5v5 seconds and attempts of all the units (lines or pairs) he belongs to and
compares them with his 5v5 totals in player_game_strength. Both are built from the same stints and the same credit
rules, so a unit sum can never be above his total (any case is a bug) and falls short only where he was on the ice
in a stint with no line or pair (for example 4 forwards). Run from the repo root with the `nhl` environment active,
after build_base_tables.py and build_line_tables.py:

    python scripts/check_line_tables.py --season 2025
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

from line_tables import is_five_on_five  # noqa: E402

KINDS = ("goal", "sog", "miss", "block")
STATS = ("seconds", "cf", "ca", "gf", "ga")


def stats_of(row):
    """seconds, Corsi and goals for and against of a row with seconds and for_/against_ counts."""
    return {
        "seconds": row["seconds"],
        "cf": sum(row[f"for_{k}"] for k in KINDS),
        "ca": sum(row[f"against_{k}"] for k in KINDS),
        "gf": row["for_goal"],
        "ga": row["against_goal"],
    }


def unit_sums(unit_rows):
    """{(player_id, team_id): Counter of STATS} adding every unit row the player is in."""
    sums = defaultdict(Counter)
    for row in unit_rows:
        values = stats_of(row)
        for player_id in row["player_ids"]:
            sums[(player_id, row["team_id"])].update(values)
    return sums


def player_totals(player_rows):
    """{(player_id, team_id): Counter of STATS} for the 5v5 state rows of player_game_strength."""
    totals = defaultdict(Counter)
    for row in player_rows:
        state = (
            row["strength"],
            row["skaters_for"],
            row["skaters_against"],
            row["goalies_for"],
            row["goalies_against"],
        )
        if is_five_on_five(state):
            totals[(row["player_id"], row["team_id"])].update(stats_of(row))
    return totals


def compare(sums, totals):
    """({stat: number of players whose unit sum is above his total}, {stat: units sum / total over all players},
    [(player, team, stat, unit sum, total) for the worst shortfalls of seconds], players in units without 5v5 rows)."""
    above, unit_total, player_total = Counter(), Counter(), Counter()
    shortfalls, missing = [], 0
    for key, mine in sums.items():
        if key not in totals:
            missing += 1
            continue
        for stat in STATS:
            unit_total[stat] += mine[stat]
            player_total[stat] += totals[key][stat]
            if mine[stat] > totals[key][stat]:
                above[stat] += 1
        shortfalls.append((totals[key]["seconds"] - mine["seconds"], key, mine["seconds"], totals[key]["seconds"]))
    share = {stat: (unit_total[stat] / player_total[stat] if player_total[stat] else None) for stat in STATS}
    shortfalls.sort(reverse=True)
    return above, share, shortfalls[:5], missing


def main():
    parser = argparse.ArgumentParser(description="Check the line and pair tables against the players' 5v5 numbers.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    metrics = REPO_ROOT / "data" / "metrics" / f"season={args.season}"
    units = pq.read_table(metrics / "unit_game_5v5.parquet").to_pylist()
    players = pq.read_table(metrics / "player_game_strength.parquet").to_pylist()
    sums, totals = unit_sums(units), player_totals(players)
    above, share, shortfalls, missing = compare(sums, totals)
    print(f"Season {args.season}: {len(sums)} skaters in lines or pairs, {len(totals)} with 5v5 time")
    print("Unit sum above the player's own total (must be 0): " + ", ".join(f"{s} {above[s]}" for s in STATS))
    print("Units' share of the players' 5v5 totals: " + ", ".join(f"{s} {100 * share[s]:.1f}%" for s in STATS))
    print(f"Skaters in a unit with no 5v5 rows of their own: {missing}")
    print(
        "Largest shortfalls in seconds (player, team: units / total): "
        + "; ".join(f"{k[0]}, {k[1]}: {mine} / {total}" for _, k, mine, total in shortfalls)
    )


if __name__ == "__main__":
    main()
