"""Why are 1.2% of the 5v5 seconds in no line or no pair? (Phase 6)

A side of a 5v5 stint has a line only with exactly 3 forwards and a pair only with exactly 2 defensemen, by the position
the boxscore gives each player for that game. This lists, for one season, which compositions (forwards, defensemen,
players without a position) the uncovered stints have, which teams have the most of them, and which players the
boxscore lists as a forward in some games and a defenseman in others. Run from the repo root with the `nhl`
environment active, after build_stints.py:

    python scripts/diagnose_unit_gaps.py --season 2025
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

from line_tables import is_five_on_five, positions_by_game  # noqa: E402
from stints import SIDES, side_state  # noqa: E402

STANDARD = (3, 2, 0)  # forwards, defensemen, players without a position


def composition(skater_ids, positions):
    """(forwards, defensemen, players without a position) among these skaters."""
    forwards = sum(positions.get(p) == "F" for p in skater_ids)
    defense = sum(positions.get(p) == "D" for p in skater_ids)
    return forwards, defense, len(skater_ids) - forwards - defense


def tally(stints_by_game, games, positions):
    """({composition: seconds}, {team_id: (seconds with a standard composition, seconds without)}) over the 5v5 sides."""
    by_composition, by_team = Counter(), defaultdict(lambda: [0, 0])
    for game_id, stints in stints_by_game.items():
        team_ids = {"home": games[game_id]["home_team_id"], "away": games[game_id]["away_team_id"]}
        for stint in stints:
            for side in SIDES:
                if not is_five_on_five(side_state(stint, side)):
                    continue
                kind = composition(stint[f"{side}_skater_ids"], positions.get(game_id, {}))
                by_composition[kind] += stint["seconds"]
                by_team[team_ids[side]][0 if kind == STANDARD else 1] += stint["seconds"]
    return by_composition, by_team


def mixed_positions(positions):
    """{player_id: (games as a forward, games as a defenseman)} for players listed as both, most games first."""
    labels = defaultdict(Counter)
    for game_positions in positions.values():
        for player_id, label in game_positions.items():
            labels[player_id][label] += 1
    mixed = {p: (c["F"], c["D"]) for p, c in labels.items() if c["F"] and c["D"]}
    return dict(sorted(mixed.items(), key=lambda item: -min(item[1])))


def main():
    parser = argparse.ArgumentParser(description="Why some 5v5 seconds are in no line or pair.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    staging = REPO_ROOT / "data" / "staging" / f"season={args.season}"
    metrics = REPO_ROOT / "data" / "metrics" / f"season={args.season}"
    games = {
        g["game_id"]: g
        for g in pq.read_table(
            staging / "games.parquet", columns=["game_id", "home_team_id", "away_team_id"]
        ).to_pylist()
    }
    positions = positions_by_game(
        pq.read_table(
            staging / "boxscore_players.parquet", columns=["game_id", "player_id", "position", "player_group"]
        ).to_pylist()
    )
    stints_by_game = defaultdict(list)
    for stint in pq.read_table(metrics / "stints.parquet").to_pylist():
        stints_by_game[stint["game_id"]].append(stint)

    by_composition, by_team = tally(stints_by_game, games, positions)
    total = sum(by_composition.values())
    print(f"Season {args.season}: 5v5 side-seconds by composition (forwards, defensemen, no position), share of all")
    for kind, seconds in by_composition.most_common(8):
        print(
            f"  {kind}  {seconds:9d} s  {100 * seconds / total:5.2f}%"
            + ("   <- a standard line and pair" if kind == STANDARD else "")
        )
    print("\nTeams with the largest share of 5v5 time without a standard composition:")
    for team_id, (standard, other) in sorted(by_team.items(), key=lambda item: -item[1][1] / (item[1][0] + item[1][1]))[
        :6
    ]:
        print(f"  team {team_id}: {100 * other / (standard + other):.1f}% ({other / 60:.0f} min)")
    mixed = mixed_positions(positions)
    print(f"\nPlayers the boxscore lists as both a forward and a defenseman: {len(mixed)}")
    for player_id, (as_forward, as_defense) in list(mixed.items())[:8]:
        print(f"  player {player_id}: {as_forward} games as a forward, {as_defense} as a defenseman")


if __name__ == "__main__":
    main()
