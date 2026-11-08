"""Tests for the player special-teams check: the per-skater sums and the comparison summary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_player_special_teams as check  # noqa: E402


def state(player=7, strength="pp", seconds=60, **numbers):
    row = {c: 0 for c in check.STATE_COLUMNS}
    row.update(numbers)
    row.update(player_id=player, strength=strength, seconds=seconds)
    return row


def test_power_play_and_shorthanded_rows_are_summed_separately_and_even_strength_is_ignored():
    rows = [
        state(strength="pp", seconds=100, ind_goal=1, ind_sog=2, ind_miss=1, ind_block=1, assists_primary=1, for_goal=1),
        state(strength="pp", seconds=50, assists_secondary=2, against_goal=0),
        state(strength="sh", seconds=30, ind_goal=1, against_goal=2),
        state(strength="ev", seconds=999, ind_goal=9),
    ]
    out = check.special_team_counts(rows)[7]
    pp, sh = out["pp"], out["sh"]
    assert pp["goals"] == 1 and pp["assists"] == 3 and pp["points"] == 4 and pp["seconds"] == 150
    assert pp["shots"] == 3 and pp["attempts"] == 5 and pp["gf"] == 1
    assert pp["fenwick"] == 4 and pp["goal_shot_block"] == 4
    assert sh["goals"] == 1 and sh["ga"] == 2 and sh["seconds"] == 30
    assert 9 not in (pp["goals"], sh["goals"])


def test_players_are_kept_apart_and_none_counts_as_zero():
    rows = [state(player=1, ind_goal=2), state(player=2, ind_goal=None, ind_sog=None)]
    out = check.special_team_counts(rows)
    assert out[1]["pp"]["goals"] == 2 and out[2]["pp"]["goals"] == 0


def test_summary_counts_exact_close_and_the_largest_gap():
    result = check.summarize([(5, 5, 1), (6, 5, 2), (10, 5, 3)])
    assert result["exact"] == 1 and result["within_2"] == 2
    assert result["ours"] == 21 and result["nhl"] == 15 and result["worst"] == (5, 3)


def test_summary_of_nothing_does_not_fail():
    result = check.summarize([])
    assert result["exact"] == 0 and result["ours"] == 0 and result["worst"] == (0, None)