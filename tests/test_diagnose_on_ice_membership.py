"""Tests for the on-ice membership diagnostic. Tiny made-up stints and goals."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import diagnose_on_ice_membership as d  # noqa: E402


def stint(start, end, home, away):
    return {"start_game_seconds": start, "end_game_seconds": end, "home_skater_ids": home, "away_skater_ids": away}


def goal(time, home=True, sf=5, sa=4, gf=1, ga=1):
    return {"game_id": 1, "game_seconds": time, "is_home": home, "skaters_for": sf, "skaters_against": sa,
            "goalie_for": gf, "goalie_against": ga}


STINTS = {1: [stint(0, 60, [1, 2], [11, 12]), stint(60, 120, [1, 3], [11, 12])]}


def test_a_power_play_goal_counts_for_the_scorers_and_against_the_shorthanded_side():
    counts = d.membership_counts(STINTS, [goal(30)])
    assert counts[(1, "pp")]["ours"] == 1 and counts[(2, "pp")]["ours"] == 1
    assert counts[(11, "sh")]["ours"] == 1
    assert (3, "pp") not in counts


def test_a_goal_at_a_line_change_gives_extra_and_lost():
    counts = d.membership_counts(STINTS, [goal(60)], window=0)
    assert counts[(2, "pp")]["ours"] == 1 and counts[(2, "pp")]["lost"] == 1  # leaves at 60: credited now, maybe not
    assert counts[(3, "pp")]["extra"] == 1 and counts[(3, "pp")]["ours"] == 0  # joins at 60: maybe on the ice
    assert counts[(1, "pp")]["lost"] == 0 and counts[(1, "pp")]["extra"] == 0  # on in both


def test_window_one_reaches_a_goal_one_second_before_the_change():
    assert (3, "pp") not in d.membership_counts(STINTS, [goal(59)], window=0)
    assert d.membership_counts(STINTS, [goal(59)], window=1)[(3, "pp")]["extra"] == 1


def test_goals_that_are_not_power_play_goals_are_ignored():
    assert not d.membership_counts(STINTS, [goal(30, sf=5, sa=5)])
    assert not d.membership_counts(STINTS, [goal(30, sf=6, sa=5, gf=0)])  # pulled goalie: even


def test_explain_counts_gaps_that_line_change_goals_could_close():
    counts = d.membership_counts(STINTS, [goal(60)], window=0)
    reference = {2: {"ppGoalsForPer60": 0.0, "ppTimeOnIce": 3600},   # NHL 0, ours 1, lost 1 -> explained
                 3: {"ppGoalsForPer60": 1.0, "ppTimeOnIce": 3600},   # NHL 1, ours 0, extra 1 -> explained
                 1: {"ppGoalsForPer60": 1.0, "ppTimeOnIce": 3600},   # exact
                 9: {"ppGoalsForPer60": 2.0, "ppTimeOnIce": 3600}}   # NHL 2, ours 0, nothing movable
    s = d.explain(counts, reference, "pp", [1, 2, 3, 9])
    assert (s["skaters"], s["exact"], s["differ"], s["explained"], s["none_movable"]) == (4, 1, 3, 2, 1)