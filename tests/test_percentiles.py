"""Tests for src/nhl_pipeline/transform/percentiles.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))

import pytest  # noqa: E402

import percentiles as pc  # noqa: E402


def display(player_id, position, goals_per_60, kind="team", team="TOR", toi=1200, **extra):
    return {"player_id": player_id, "name": f"P{player_id}", "position": position, "kind": kind, "team": team,
            "teams": team, "goals_per_60": goals_per_60, "toi_per_game_seconds": toi, **extra}


def advanced(player_id, minutes, ca_per_60=50.0, situation="5v5", kind="team", **extra):
    return {"player_id": player_id, "situation": situation, "kind": kind, "seconds": minutes * 60,
            "ca_per_60": ca_per_60, **extra}


def rows_for(rows, stat):
    return {r["player_id"]: r for r in rows if r["stat"] == stat}


GOALS_AND_CA = [s for s in pc.STATS if s[0] in ("goals_per_60", "ca_per_60", "toi_per_game")]


def test_percentile_rank_shares_ties_and_can_be_reversed():
    pool = [1, 2, 2, 4]
    assert pc.percentile_rank(4, pool) == 87.5 and pc.percentile_rank(1, pool) == 12.5
    assert pc.percentile_rank(2, pool) == 50.0
    assert pc.percentile_rank(1, pool, higher_is_better=False) == 87.5
    assert pc.percentile_rank(None, pool) is None and pc.percentile_rank(3, []) is None


def test_positions_group_into_forwards_and_defensemen_only():
    assert [pc.position_group(p) for p in ("C", "L", "R", "D", "G", None)] == ["F", "F", "F", "D", None, None]


def test_forwards_and_defensemen_are_ranked_in_their_own_pool_and_a_player_below_the_minimum_is_not_in_it():
    shown = [display(1, "C", 1.0), display(2, "L", 2.0), display(3, "R", 3.0), display(4, "D", 0.2),
             display(5, "D", 0.4), display(6, "C", 9.0)]
    adv = [advanced(i, 700) for i in (1, 2, 3, 4, 5)] + [advanced(6, 100)]
    rows = rows_for(pc.build_percentile_rows(2025, shown, adv, stats=GOALS_AND_CA), "goals_per_60")
    assert rows[3]["percentile"] == pytest.approx(250 / 3) and rows[1]["percentile"] == pytest.approx(50 / 3)
    assert rows[5]["percentile"] == 75.0 and rows[4]["percentile"] == 25.0   # defensemen only against defensemen
    assert rows[1]["pool_size"] == 3 and rows[5]["pool_size"] == 2
    assert rows[6]["in_pool"] is False and rows[6]["percentile"] == 100.0     # ranked against the pool, not part of it
    assert rows[6]["minutes_5v5"] == 100.0


def test_a_stat_where_fewer_is_better_is_reversed_and_time_on_ice_is_in_minutes():
    shown = [display(1, "C", 1, toi=1200), display(2, "C", 1, toi=900), display(3, "C", 1, toi=1080)]
    adv = [advanced(1, 700, ca_per_60=40.0), advanced(2, 700, ca_per_60=60.0), advanced(3, 700, ca_per_60=50.0)]
    rows = pc.build_percentile_rows(2025, shown, adv, stats=GOALS_AND_CA)
    ca = rows_for(rows, "ca_per_60")
    assert (ca[1]["percentile"], ca[3]["percentile"], ca[2]["percentile"]) == pytest.approx((250 / 3, 50.0, 50 / 3))
    toi = rows_for(rows, "toi_per_game")
    assert toi[1]["value"] == 20.0 and toi[1]["percentile"] > toi[2]["percentile"]


def test_a_traded_player_counts_once_with_his_combined_rows_and_missing_5v5_rows_leave_those_stats_empty():
    shown = [display(1, "C", 1.0, kind="team", team="TOR"), display(1, "C", 3.0, kind="team", team="BOS"),
             display(1, "C", 2.0, kind="total", team="TOT"), display(2, "C", 1.0)]
    adv = [advanced(1, 300, kind="team"), advanced(1, 300, kind="team"), advanced(1, 650, kind="total")]
    rows = pc.build_percentile_rows(2025, shown, adv, stats=GOALS_AND_CA)
    goals = rows_for(rows, "goals_per_60")
    assert len(goals) == 2 and goals[1]["value"] == 2.0 and goals[1]["team"] == "TOT" and goals[1]["in_pool"]
    ca = rows_for(rows, "ca_per_60")
    assert ca[2]["value"] is None and ca[2]["percentile"] is None and goals[2]["in_pool"] is False


def test_default_charts_have_eight_known_stats_each_and_flag_the_rows_that_belong_to_them():
    for group in pc.GROUPS:
        assert len(pc.DEFAULT_CHART[group]) == 8 and set(pc.DEFAULT_CHART[group]) <= set(pc.STATS_BY_KEY)
    shown = [display(1, "D", 1.0)]
    rows = pc.build_percentile_rows(2025, shown, [advanced(1, 700)], stats=GOALS_AND_CA)
    assert {r["stat"]: r["in_default_chart"] for r in rows} == {
        "goals_per_60": True, "ca_per_60": True, "toi_per_game": False}