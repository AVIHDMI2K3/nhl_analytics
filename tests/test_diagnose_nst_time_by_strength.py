"""Tests for the helpers of scripts/diagnose_nst_time_by_strength.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import diagnose_nst_time_by_strength as d  # noqa: E402


def row(team, strength, sf, sa, gf, ga, seconds):
    return {"team_id": team, "strength": strength, "skaters_for": sf, "skaters_against": sa,
            "goalies_for": gf, "goalies_against": ga, "seconds": seconds}


def test_even_strength_states_are_split_into_parts_and_other_strengths_are_left_out():
    rows = [row(1, "ev", 5, 5, 1, 1, 600), row(1, "ev", 4, 4, 1, 1, 120), row(1, "ev", 3, 3, 1, 1, 60),
            row(1, "ev", 5, 5, 0, 1, 30), row(1, "pp", 5, 4, 1, 1, 999), row(2, "ev", 5, 5, 1, 1, 60)]
    minutes = d.minutes_by_team(rows)
    assert minutes[1]["5v5"] == 10 and minutes[1]["4v4"] == 2 and minutes[1]["3v3"] == 1 and minutes[1]["goalie out"] == 0.5
    assert "pp" not in minutes[1] and minutes[2]["5v5"] == 1


def test_what_nst_leaves_for_4v4_is_ev_minus_5v5_and_3v3():
    ours = d.minutes_by_team([row(1, "ev", 5, 5, 1, 1, 600), row(1, "ev", 4, 4, 1, 1, 120), row(1, "ev", 3, 3, 1, 1, 60)])
    ours = {"AAA": ours[1]}
    table = d.compare(ours, {"AAA": 10.2}, {"AAA": 13.0}, {"AAA": 0.9})
    row_ = table["AAA"]
    assert round(row_["nst_4v4_rest"], 1) == 1.9 and round(row_["ours_4v4_rest"], 1) == 2.0
    assert round(row_["ours_ev"], 1) == 13.0 and d.compare(ours, {}, {}, {}) == {}