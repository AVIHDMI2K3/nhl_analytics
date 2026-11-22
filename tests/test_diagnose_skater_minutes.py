"""Tests for scripts/diagnose_skater_minutes.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import diagnose_skater_minutes as dm  # noqa: E402


def test_a_traded_player_counts_once_with_his_combined_row():
    rows = [
        {"player_id": 1, "kind": "team", "seconds": 10},
        {"player_id": 1, "kind": "total", "seconds": 30},
        {"player_id": 1, "kind": "team", "seconds": 20},
        {"player_id": 2, "kind": "team", "seconds": 5},
    ]
    chosen = {r["player_id"]: r["seconds"] for r in dm.one_row_per_player(rows)}
    assert chosen == {1: 30, 2: 5}


def test_positions_are_grouped_as_forwards_and_defensemen_and_goalies_are_left_out():
    assert [dm.position_group(p) for p in ("C", "L", "R", "D", "G", None)] == ["F", "F", "F", "D", None, None]


def test_minutes_are_described_with_the_number_of_skaters_at_each_minimum():
    d = dm.describe_minutes([100, 250, 450, 700, 1100], thresholds=(200, 600))
    assert d["skaters"] == 5 and d["median"] == 450 and d["mean"] == 520 and d["at_least"] == {200: 4, 600: 2}
    assert dm.describe_minutes([], thresholds=(200,))["at_least"] == {200: 0}
