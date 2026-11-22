"""Tests for the helpers of scripts/check_line_tables.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import check_line_tables as c  # noqa: E402


def counts(seconds, cf_goal=0, cf_sog=0, ca_sog=0):
    return {
        "seconds": seconds,
        "for_goal": cf_goal,
        "for_sog": cf_sog,
        "for_miss": 0,
        "for_block": 0,
        "against_goal": 0,
        "against_sog": ca_sog,
        "against_miss": 0,
        "against_block": 0,
    }


def unit(team, ids, **kw):
    return {"team_id": team, "player_ids": ids, **counts(**kw)}


def player(player_id, team, seconds, state=(5, 5, 1, 1), **kw):
    return {
        "player_id": player_id,
        "team_id": team,
        "strength": "ev",
        "skaters_for": state[0],
        "skaters_against": state[1],
        "goalies_for": state[2],
        "goalies_against": state[3],
        **counts(seconds, **kw),
    }


def test_unit_sums_add_every_unit_a_player_is_in():
    sums = c.unit_sums([unit(1, [1, 2, 3], seconds=60, cf_sog=2), unit(1, [1, 2, 6], seconds=30, cf_sog=1, cf_goal=1)])
    assert sums[(1, 1)]["seconds"] == 90 and sums[(1, 1)]["cf"] == 4 and sums[(1, 1)]["gf"] == 1
    assert sums[(3, 1)]["seconds"] == 60 and (6, 1) in sums


def test_player_totals_use_only_five_on_five_rows():
    rows = [
        player(1, 1, 100, cf_sog=5),
        player(1, 1, 40, state=(5, 5, 0, 1), cf_sog=9),
        player(1, 1, 20, state=(5, 4, 1, 1)),
    ]
    assert c.player_totals(rows)[(1, 1)]["seconds"] == 100 and c.player_totals(rows)[(1, 1)]["cf"] == 5


def test_the_comparison_reports_shares_violations_and_shortfalls():
    sums = c.unit_sums([unit(1, [1, 2, 3], seconds=90, cf_sog=4), unit(1, [4, 5], seconds=70, cf_sog=3)])
    totals = c.player_totals(
        [
            player(1, 1, 100, cf_sog=4),
            player(2, 1, 90, cf_sog=4),
            player(3, 1, 90, cf_sog=4),
            player(4, 1, 60, cf_sog=3),
        ]
    )  # player 4: the unit says 70 s against 60 in his own rows
    above, share, shortfalls, missing = c.compare(sums, totals)
    assert above["seconds"] == 1 and above["cf"] == 0 and missing == 1  # player 5 has no rows of his own
    assert round(share["seconds"], 3) == round((90 + 90 + 90 + 70) / (100 + 90 + 90 + 60), 3)
    assert shortfalls[0][1] == (1, 1) and shortfalls[0][0] == 10
