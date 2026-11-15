"""Tests for the helpers of scripts/compare_html_shifts.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import compare_html_shifts as c  # noqa: E402


def row(player, start, end):
    return {"player_id": player, "start_game_seconds": start, "end_game_seconds": end}


def test_players_are_compared_by_shift_count_seconds_and_identical_shifts():
    api = [row(1, 0, 30), row(1, 60, 90), row(2, 0, 10)]
    html = [row(1, 0, 30), row(1, 61, 90), row(3, 5, 15)]
    result = c.compare_players(api, html)
    assert result[1] == (2, 2, 60, 59, 1)
    assert result[2] == (1, 0, 10, 0, 0) and result[3] == (0, 1, 0, 10, 0)