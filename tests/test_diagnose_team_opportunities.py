"""Tests for the opportunity counting. Made-up penalties, no real data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import diagnose_team_opportunities as d  # noqa: E402


def pen(team, second, minutes=2, game=1):
    return {"game_id": game, "game_seconds": second, "event_owner_team_id": team,
            "penalty_minutes": minutes, "opponent_team_id": 2 if team == 1 else 1}


def test_each_minor_gives_the_other_team_an_opportunity():
    opp, short = d.count_opportunities([pen(1, 100), pen(1, 500), pen(2, 900)])
    assert (opp[2], opp[1], short[1], short[2]) == (2, 1, 2, 1)


def test_misconducts_and_zero_minute_rows_are_not_counted():
    opp, _ = d.count_opportunities([pen(1, 100, 10), pen(1, 200, 0), pen(1, 300, None)])
    assert not opp


def test_offsetting_penalties_cancel_only_with_offset():
    rows = [pen(1, 100), pen(2, 100)]
    assert d.count_opportunities(rows)[0][1] == 1
    opp, short = d.count_opportunities(rows, offset=True)
    assert opp[1] == 0 and opp[2] == 0 and short[1] == 0


def test_offset_needs_the_same_length_and_second():
    opp, _ = d.count_opportunities([pen(1, 100, 2), pen(2, 100, 5), pen(2, 101, 2)], offset=True)
    assert opp[1] == 2 and opp[2] == 1


def test_compare_counts_exact_teams_and_totals():
    assert d.compare({1: 10, 2: 9}, {1: 10, 2: 11}) == (1, 2, 19, 21)


def test_majors_can_be_left_out_of_the_offset_and_double_minors_counted_twice():
    rows = [pen(1, 100, 5), pen(2, 100, 5)]
    assert d.count_opportunities(rows, offset=True)[0][1] == 0
    assert d.count_opportunities(rows, offset=True, offset_majors=False)[0][1] == 1
    assert d.count_opportunities([pen(1, 100, 4)], double_minor_twice=True)[0][2] == 2


def test_cancelled_pairs_are_counted_by_minutes_and_type():
    rows = [{**pen(1, 100, 5), "penalty_type_code": "MAJ"}, {**pen(2, 100, 5), "penalty_type_code": "MAJ"},
            {**pen(1, 200), "penalty_type_code": "MIN"}, {**pen(2, 200), "penalty_type_code": "BEN"},
            {**pen(1, 300), "penalty_type_code": "MIN"}]
    assert d.cancelled_pairs(rows) == {(5, "MAJ", "MAJ"): 1, (2, "BEN", "MIN"): 1}


def test_a_double_minor_split_into_two_minors_is_cancelled_one_for_one():
    rows = [pen(1, 100, 4), pen(2, 100, 2)]
    opp, short = d.count_opportunities(rows, offset=True, split_double_minors=True)
    assert opp[2] == 1 and opp[1] == 0 and short[1] == 1  # one of the two minors is left
    assert d.count_opportunities([pen(1, 100, 4)], offset=True, split_double_minors=True)[0][2] == 2
    assert d.count_opportunities(rows, offset=True)[0][1] == 1  # without the split nothing cancels


def clock(rows, **kw):
    return d.count_opportunities_clock(rows, **kw)


def test_clock_cancels_same_second_penalties_and_counts_a_double_minor_twice():
    opp, short = clock([pen(1, 100), pen(2, 100)])
    assert not opp
    opp, _ = clock([pen(1, 100, 4)])
    assert opp[2] == 2
    opp, _ = clock([pen(1, 100, 4), pen(2, 100, 2)])  # one of the two minors is left
    assert opp[2] == 1 and opp[1] == 0


def test_clock_cancels_a_penalty_taken_while_the_other_team_is_shorthanded():
    opp, _ = clock([pen(1, 100), pen(2, 160)])  # team 1 is down a man until 220
    assert opp[2] == 1 and opp[1] == 0
    opp, _ = clock([pen(1, 100), pen(2, 300)])  # team 1's penalty is over
    assert opp[2] == 1 and opp[1] == 1
    opp, _ = clock([pen(1, 100), pen(1, 110), pen(2, 150)])  # down two men, one comes back
    assert opp[2] == 2 and opp[1] == 0


def test_two_penalties_are_served_at_once_and_a_third_waits():
    # minors at 100, 110 and 120: the third waits until 220, so a penalty to the other team at 230 still offsets
    opp, _ = clock([pen(1, 100), pen(1, 110), pen(1, 120), pen(2, 230)])
    assert opp[2] == 3 and opp[1] == 0
    # with only two, both are over by 230
    opp, _ = clock([pen(1, 100), pen(1, 110), pen(2, 230)])
    assert opp[2] == 2 and opp[1] == 1


def test_the_second_half_of_a_double_minor_waits_for_the_first():
    # team 1's double minor at 100 runs 100-220 and 220-340; team 2's penalty at 300 is taken while it is shorthanded
    opp, _ = clock([pen(1, 100, 4), pen(2, 300)])
    assert opp[2] == 2 and opp[1] == 0


def test_expiry_steps_count_a_power_play_left_after_the_other_penalty_runs_out():
    # team 1 is shorthanded 100-220, team 2 from 160 to 280: team 1 has the advantage 220-280
    rows = [pen(1, 100), pen(2, 160)]
    assert clock(rows)[0][1] == 0
    assert clock(rows, steps=True)[0][1] == 1
    # a major against a coincident minor: the minor ends first and leaves the major's power play
    rows = [pen(1, 100, 2), pen(2, 100, 5)]
    assert not clock(rows)[0] and clock(rows, steps=True)[0][1] == 1


def test_penalties_at_the_end_of_regulation_can_be_ignored():
    rows = [{**pen(1, 3600), "period_type": "REG", "game_has_ot": False},
            {**pen(2, 3600, game=2), "period_type": "REG", "game_has_ot": True}]
    assert d.count_opportunities(rows)[0][2] == 1 and d.count_opportunities(rows)[0][1] == 1
    assert not d.count_opportunities(rows, ignore_end="regulation")[0]
    assert d.count_opportunities(rows, ignore_end="no_overtime")[0][1] == 1  # only the overtime game's
    assert not clock(rows, ignore_end="regulation")[0]


def test_a_minor_does_not_count_against_a_major_at_the_same_second():
    rows = [pen(1, 100, 2), pen(2, 100, 5)]
    opp, short = d.count_opportunities(rows, offset=True, minor_vs_major=True)
    assert opp[1] == 1 and opp[2] == 0  # the major still gives team 1 its opportunity
    opp, _ = d.count_opportunities(rows, offset=True)
    assert opp[1] == 1 and opp[2] == 1


def test_late_penalties_are_left_out_only_in_games_without_overtime():
    rows = [{**pen(1, 3590), "period_type": "REG", "game_has_ot": False},
            {**pen(1, 3590, game=2), "period_type": "REG", "game_has_ot": True},
            {**pen(1, 3000), "period_type": "REG", "game_has_ot": False}]
    assert d.count_opportunities(rows, late_seconds=20)[0][2] == 2
    assert d.count_opportunities(rows, late_seconds=5)[0][2] == 3