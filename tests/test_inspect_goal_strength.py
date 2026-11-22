"""Tests for the goal-strength inspector's helpers. Made-up stints and events."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import inspect_goal_strength as inspect_goals  # noqa: E402


def stint(start, end, home=5, away=4, home_strength="ev", away_strength="ev"):
    return {
        "start_game_seconds": start,
        "end_game_seconds": end,
        "home_real_skaters": home,
        "away_real_skaters": away,
        "home_strength": home_strength,
        "away_strength": away_strength,
    }


def test_a_goal_belongs_to_the_stint_that_ends_on_its_second():
    stints = [stint(0, 100, home_strength="pp"), stint(100, 200, home_strength="ev")]
    assert inspect_goals.stint_at(stints, 100)["home_strength"] == "pp"
    assert inspect_goals.stint_at(stints, 101)["home_strength"] == "ev"
    assert inspect_goals.stint_at(stints, 0) is None and inspect_goals.stint_at(stints, 201) is None


def test_the_view_is_from_the_scoring_side():
    s = stint(0, 100, home=5, away=4, home_strength="pp", away_strength="sh")
    assert inspect_goals.our_view(s, True) == (5, 4, "pp")
    assert inspect_goals.our_view(s, False) == (4, 5, "sh")
    assert inspect_goals.our_view(None, True) == (None, None, None)


def test_only_penalties_in_the_window_before_the_goal_are_listed():
    events = [
        {"event_type": "penalty", "game_seconds": 100},
        {"event_type": "penalty", "game_seconds": 800},
        {"event_type": "penalty", "game_seconds": 1000},  # after the goal
        {"event_type": "goal", "game_seconds": 900},
    ]
    found = inspect_goals.recent_penalties(events, 900)
    assert [e["game_seconds"] for e in found] == [800]
