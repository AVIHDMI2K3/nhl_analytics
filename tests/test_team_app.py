"""Tests for src/nhl_pipeline/transform/team_app.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))

import pytest  # noqa: E402
import team_app as ta  # noqa: E402


def basic(team_id, team, points, goal_diff=0, season=2025):
    row = {"season": season, "team_id": team_id, "team": team}
    row.update({c: 0 for c in ta.BASIC_COLUMNS})
    row.update(
        {
            "points": points,
            "goal_diff": goal_diff,
            "points_pct": 0.6097560975609756,
            "shots_for_per_game": 27.024390243902438,
            "shots_against_per_game": 29.670731707317074,
        }
    )
    return row


def advanced(team_id, situation="5v5", cf_pct=48.93, season=2025):
    row = {"season": season, "team_id": team_id, "team": "X", "situation": situation}
    row.update({c: 1 for c in ta.ADVANCED_COLUMNS})
    row["cf_pct"] = cf_pct
    return row


def special(team_id, pp_pct=23.305, pk_pct=77.06, season=2025):
    row = {"season": season, "team_id": team_id, "team": "X"}
    row.update({c: 1 for c in ta.SPECIAL_COLUMNS})
    row.update({"pp_pct": pp_pct, "pk_pct": pk_pct})
    return row


def test_joins_the_three_tables_and_uses_only_the_5v5_row():
    rows = ta.build_team_rows(
        [basic(6, "BOS", 100)], [advanced(6, "all", cf_pct=60.0), advanced(6, "5v5", cf_pct=48.93)], [special(6)]
    )
    assert len(rows) == 1
    assert rows[0]["cf_pct_5v5"] == pytest.approx(48.9)
    assert rows[0]["pp_pct"] == pytest.approx(23.3)


def test_rounding():
    row = ta.build_team_rows([basic(6, "BOS", 100)], [advanced(6)], [special(6)])[0]
    assert row["points_pct"] == pytest.approx(0.610)
    assert row["shots_for_per_game"] == pytest.approx(27.0)
    assert row["pk_pct"] == pytest.approx(77.1)


def test_every_5v5_column_has_the_suffix():
    row = ta.build_team_rows([basic(6, "BOS", 100)], [advanced(6)], [special(6)])[0]
    for col in ta.ADVANCED_COLUMNS:
        assert f"{col}_5v5" in row
        assert col not in row


def test_sorted_by_points_then_goal_difference():
    rows = ta.build_team_rows(
        [basic(1, "AAA", 90, goal_diff=5), basic(2, "BBB", 100), basic(3, "CCC", 90, goal_diff=20)], [], []
    )
    assert [r["team"] for r in rows] == ["BBB", "CCC", "AAA"]


def test_team_without_5v5_or_special_teams_row_is_kept_with_none():
    row = ta.build_team_rows([basic(6, "BOS", 100)], [advanced(7)], [special(7)])[0]
    assert row["cf_pct_5v5"] is None
    assert row["pp_pct"] is None
    assert row["points"] == 100


def test_seasons_do_not_mix():
    rows = ta.build_team_rows([basic(6, "BOS", 100, season=2024)], [advanced(6, season=2025, cf_pct=70.0)], [])
    assert rows[0]["cf_pct_5v5"] is None


def test_team_names():
    assert ta.team_name("TOR", 2025) == "Toronto Maple Leafs"
    assert ta.team_name("UTA", 2025) == "Utah Mammoth"
    assert ta.team_name("UTA", 2024) == "Utah Hockey Club"
    assert ta.team_name("ZZZ", 2025) == "ZZZ"
    assert len(ta.TEAM_NAMES) == 33
