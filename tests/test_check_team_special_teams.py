"""Tests for the helpers of scripts/check_team_special_teams.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import check_team_special_teams as c  # noqa: E402


def test_compare_counts_exact_keys_totals_and_the_worst_difference():
    exact, total, mine, theirs, worst = c.compare({"a": 3, "b": 1, "c": 5}, {"a": 3, "b": 2, "c": 2, "d": 0})
    assert (exact, total, mine, theirs, worst) == (2, 4, 9, 7, 3)


def test_percentages_are_read_as_fractions_or_percent():
    assert c.as_percent(0.2113) == 21.13
    assert c.as_percent(21.13) == 21.13
    assert c.as_percent(None) is None