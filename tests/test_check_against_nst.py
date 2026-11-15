"""Tests for the helpers of scripts/check_against_nst.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import check_against_nst as c  # noqa: E402


def test_names_and_teams_are_normalized():
    assert c.normalize_name("Alexis Lafrenière") == c.normalize_name("Alexis Lafreniere")
    assert c.normalize_name("J.T. Miller") == "jt miller" and c.normalize_name("Jean-Gabriel Pageau") == "jean gabriel pageau"
    assert c.team_set("CGY, ANA") == c.team_set("ANA, CGY") == frozenset({"CGY", "ANA"})
    assert c.team_set("S.J") == frozenset({"SJS"}) and c.team_set('"T.B"') == frozenset({"TBL"})
    assert c.TEAM_NAMES[c.normalize_name("St Louis Blues")] == "STL"


def test_numbers_and_comparison():
    assert c.number("13.5") == 13.5 and c.number("-") is None and c.number(None) is None
    compared, exact, mine, theirs, worst, who = c.compare_column([(5, 5, "a"), (7, 4, "b"), (None, 3, "c"), (2, None, "d")])
    assert (compared, exact, mine, theirs, worst, who) == (2, 1, 12, 9, 3, "b")
    assert c.within([(5, 5, "a"), (7, 4, "b"), (None, 3, "c"), (6, 4, "d")], 2) == 2
    assert c.last_name("Nicholas Paul") == c.last_name("Nick Paul") == "paul"


def test_skaters_match_by_name_and_team_then_by_games_and_time():
    ours = [{"name": "Alex Smith", "teams": "NYR", "games_played": 10, "seconds": 600},
            {"name": "Jo Trader", "teams": "ANA, CGY", "games_played": 20, "seconds": 1200},
            {"name": "Sam Different", "teams": "BOS", "games_played": 30, "seconds": 1800}]
    nst = [{"Player": "Alex Smith", "Team": "NYR", "GP": "10", "TOI": "10"},
           {"Player": "Jo Trader", "Team": "CGY, ANA", "GP": "20", "TOI": "20"},
           {"Player": "Samuel Different", "Team": "BOS", "GP": "30", "TOI": "30.2"},
           {"Player": "Nobody", "Team": "TOR", "GP": "1", "TOI": "1"}]
    matched, unmatched, spare = c.match_skaters(nst, ours)
    assert sorted(matched) == [0, 1, 2] and unmatched == [3] and spare == []
    assert matched[2]["name"] == "Sam Different"