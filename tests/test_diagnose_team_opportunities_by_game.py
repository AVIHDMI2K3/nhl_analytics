"""Tests for the per-game opportunity comparison. Made-up penalties."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import diagnose_team_opportunities_by_game as d  # noqa: E402


def pen(team, second, minutes=2, game=1, code="MIN", period="REG"):
    return {
        "game_id": game,
        "game_seconds": second,
        "event_owner_team_id": team,
        "penalty_minutes": minutes,
        "opponent_team_id": 2 if team == 1 else 1,
        "penalty_type_code": code,
        "period_type": period,
    }


def test_counts_are_kept_per_game_and_team():
    opp, short = d.per_game_counts([pen(1, 10), pen(1, 20, game=2), pen(2, 30)], offset=True)
    assert opp == {(1, 2): 1, (2, 2): 1, (1, 1): 1}
    assert short == {(1, 1): 1, (2, 1): 1, (1, 2): 1}


def test_compare_counts_exact_team_games_and_the_differences():
    exact, total, diffs = d.compare({(1, 1): 2, (1, 2): 1}, {(1, 1): 2, (1, 2): 2, (2, 1): 1})
    assert (exact, total) == (1, 3)
    assert dict(diffs) == {0: 1, -1: 2}


def test_features_name_what_is_in_the_game_for_a_team():
    rows = [pen(2, 100, 4), pen(2, 100, 2, code="BEN"), pen(1, 100, 5, code="MAJ"), pen(2, 150, 10, code="MIS")]
    assert d.game_features(rows, 1) >= {
        "opponent double minor (4 min)",
        "opponent bench minor",
        "own major",
        "two opponent penalties at the same second",
        "both teams penalized at the same second",
        "opponent penalties within 2 minutes of each other",
        "misconduct or penalty shot in the game",
    }
    assert d.game_features([pen(2, 100)], 1) == set()


def test_feature_table_counts_team_games_and_disagreements():
    penalties = d.by_game([pen(2, 100, 4)])
    table = d.feature_table({(1, 1): 2, (1, 2): 0}, {(1, 1): 1}, penalties)
    assert table["all team-games"] == [2, 1]
    assert table["opponent double minor (4 min)"] == [1, 1]
    assert table["none of these"] == [1, 0]
