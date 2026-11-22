"""Tests for src/nhl_pipeline/transform/player_app.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))

import player_app as pa_  # noqa: E402
import pytest  # noqa: E402


def ident(player_id, kind="team", team_id=10, season=2025):
    return {"season": season, "player_id": player_id, "kind": kind, "team_id": team_id}


def display(player_id, points=50, name=None, **kw):
    return {
        **ident(player_id, **kw),
        "name": name or f"P{player_id}",
        "team": "TOR",
        "teams": "TOR",
        "games_played": 80,
        "goals": 20,
        "assists": 30,
        "points": points,
    }


def advanced(player_id, situation="5v5", seconds=3600, cf_pct=54.94, **kw):
    row = {**ident(player_id, **kw), "situation": situation, "seconds": seconds}
    for _, src, _ in pa_.ADVANCED_5V5:
        row.setdefault(src, 1)
    row["cf_pct"] = cf_pct
    return row


def special(player_id, situation, seconds=600, **kw):
    row = {**ident(player_id, **kw), "situation": situation, "seconds": seconds}
    for spec in (pa_.POWER_PLAY, pa_.PENALTY_KILL):
        for _, src, _ in spec:
            row.setdefault(src, 2)
    return row


def faceoffs(player_id, situation="all", **kw):
    return {**ident(player_id, **kw), "situation": situation, "faceoffs": 100, "faceoff_wins": 55, "faceoff_pct": 55.0}


def test_joins_the_right_situation_row_from_each_table():
    rows = pa_.build_player_rows(
        [display(1)],
        [advanced(1, "all", cf_pct=99.0), advanced(1, "5v5", cf_pct=54.94)],
        [special(1, "pp", seconds=300), special(1, "sh", seconds=120), special(1, "ev", seconds=9999)],
        [faceoffs(1, "5v5"), faceoffs(1, "all")],
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["cf_pct_5v5"] == pytest.approx(54.9)
    assert r["minutes_5v5"] == pytest.approx(60.0)
    assert r["pp_minutes"] == pytest.approx(5.0)
    assert r["pk_minutes"] == pytest.approx(2.0)
    assert r["fo_faceoffs"] == 100


def test_display_columns_are_kept_as_they_are():
    r = pa_.build_player_rows([display(1)], [], [], [])[0]
    assert r["goals"] == 20 and r["points"] == 50 and r["name"] == "P1"


def test_missing_rows_become_none_and_the_player_is_kept():
    r = pa_.build_player_rows([display(1)], [advanced(2)], [special(2, "pp")], [faceoffs(2)])[0]
    for col in ("minutes_5v5", "cf_pct_5v5", "pp_minutes", "pk_minutes", "fo_faceoffs", "fo_pct"):
        assert r[col] is None


def test_team_row_and_total_row_do_not_mix():
    rows = pa_.build_player_rows(
        [display(1, kind="team", team_id=10), display(1, kind="total", team_id=None, points=70)],
        [advanced(1, kind="team", team_id=10, cf_pct=50.0), advanced(1, kind="total", team_id=None, cf_pct=60.0)],
        [],
        [],
    )
    by_kind = {r["kind"]: r for r in rows}
    assert by_kind["team"]["cf_pct_5v5"] == pytest.approx(50.0)
    assert by_kind["total"]["cf_pct_5v5"] == pytest.approx(60.0)


def test_seasons_do_not_mix():
    r = pa_.build_player_rows([display(1, season=2024)], [advanced(1, season=2025)], [], [])[0]
    assert r["cf_pct_5v5"] is None


def test_column_prefixes_and_suffixes():
    r = pa_.build_player_rows([display(1)], [advanced(1)], [special(1, "pp"), special(1, "sh")], [faceoffs(1)])[0]
    for out, _, _ in pa_.ADVANCED_5V5:
        assert out.endswith("_5v5") and out in r
    for out, _, _ in pa_.POWER_PLAY:
        assert out.startswith("pp_") and out in r
    for out, _, _ in pa_.PENALTY_KILL:
        assert out.startswith("pk_") and out in r
    for out, _, _ in pa_.FACEOFFS:
        assert out.startswith("fo_") and out in r


def test_sorted_by_points_then_name():
    rows = pa_.build_player_rows([display(1, 40, "Bob"), display(2, 60, "Zed"), display(3, 40, "Al")], [], [], [])
    assert [r["name"] for r in rows] == ["Zed", "Al", "Bob"]
