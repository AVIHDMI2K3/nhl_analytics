"""Tests for the helpers of scripts/diagnose_nst_5v5.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import diagnose_nst_5v5 as d  # noqa: E402


def stint(start, end, home=5, away=5, strength="ev", home_goalie=1, away_goalie=1):
    return {
        "start_game_seconds": start,
        "end_game_seconds": end,
        "seconds": end - start,
        "home_strength": strength,
        "away_strength": strength,
        "home_skater_ids": list(range(home)),
        "away_skater_ids": list(range(100, 100 + away)),
        "home_goalie_ids": [1] * home_goalie,
        "away_goalie_ids": [2] * away_goalie,
    }


def attempt(kind, second, sf=5, sa=5, gf=1, ga=1, game=1):
    return {
        "game_id": game,
        "game_seconds": second,
        "attempt_type": kind,
        "team_id": 10,
        "opponent_team_id": 20,
        "is_home": True,
        "skaters_for": sf,
        "skaters_against": sa,
        "goalie_for": gf,
        "goalie_against": ga,
    }


def test_attempts_are_counted_under_both_rules_and_the_differences_are_listed():
    stints = {1: [stint(0, 100), stint(100, 200, home=5, away=4, strength="ev")]}
    attempts = [
        attempt("shot-on-goal", 50),  # 5v5 under both
        attempt("goal", 100),  # goal at 100 belongs to the stint ending there: 5v5 both
        attempt("missed-shot", 150, sa=5),  # code says 5v5, the stint (5v4 here) does not
        attempt("blocked-shot", 160, sa=4),  # neither
    ]
    counts, differing = d.count_five_on_five(attempts, stints)
    assert counts["code"][(10, "cf")] == 3 and counts["stint"][(10, "cf")] == 2
    assert counts["code"][(20, "ca")] == 3 and counts["code"][(10, "ff")] == 3 and counts["code"][(10, "sf")] == 2
    assert counts["code"][(10, "gf")] == 1 and counts["stint"][(20, "ga")] == 1
    assert (
        [x["attempt"]["game_seconds"] for x in differing] == [150]
        and differing[0]["by_code"]
        and not differing[0]["by_stint"]
    )


def test_five_on_five_minutes_need_five_skaters_and_a_goalie_each():
    stints = {1: [stint(0, 100), stint(100, 160, away=4), stint(160, 200, away_goalie=0)]}
    minutes = d.five_on_five_minutes(stints, {1: {"home": 10, "away": 20}})
    assert minutes == {10: 100 / 60, 20: 100 / 60}
