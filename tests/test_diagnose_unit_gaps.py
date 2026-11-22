"""Tests for the helpers of scripts/diagnose_unit_gaps.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import diagnose_unit_gaps as d  # noqa: E402

POSITIONS = {1: "F", 2: "F", 3: "F", 4: "D", 5: "D", 6: "D", 11: "F", 12: "F", 13: "F", 14: "D", 15: "D"}


def stint(seconds, home, away=(11, 12, 13, 14, 15), strength="ev"):
    return {
        "seconds": seconds,
        "home_skater_ids": list(home),
        "away_skater_ids": list(away),
        "home_goalie_ids": [30],
        "away_goalie_ids": [40],
        "home_strength": strength,
        "away_strength": strength,
    }


def test_a_composition_counts_forwards_defensemen_and_unknowns():
    assert d.composition([1, 2, 3, 4, 5], POSITIONS) == (3, 2, 0)
    assert d.composition([1, 2, 4, 5, 6], POSITIONS) == (2, 3, 0)
    assert d.composition([1, 2, 3, 4, 99], POSITIONS) == (3, 1, 1)


def test_five_on_five_time_is_tallied_by_composition_and_team():
    games = {1: {"home_team_id": 7, "away_team_id": 8}}
    stints = {
        1: [
            stint(60, (1, 2, 3, 4, 5)),
            stint(40, (1, 2, 4, 5, 6)),
            stint(500, (1, 2, 3, 4, 5), away=(11, 12, 13, 14), strength="pp"),
        ]
    }
    by_composition, by_team = d.tally(stints, games, {1: POSITIONS})
    assert by_composition == {(3, 2, 0): 60 + 60 + 40, (2, 3, 0): 40}  # the 5v4 stint is left out
    assert by_team[7] == [60, 40] and by_team[8] == [100, 0]


def test_players_listed_as_both_forward_and_defenseman_are_found():
    positions = {1: {5: "F", 6: "D"}, 2: {5: "D", 6: "D"}, 3: {5: "F", 7: "F"}}
    assert d.mixed_positions(positions) == {5: (2, 1)}
