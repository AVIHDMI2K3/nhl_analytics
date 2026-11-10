"""Tests for the faceoff logic. Made-up events, no real data."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import check_player_faceoffs as c  # noqa: E402
import faceoffs as f  # noqa: E402

GAMES = {1: {"home_team_id": 10, "away_team_id": 20}}


def faceoff(winner, loser, owner=10, zone="O", code="1551", game=1, kind="faceoff"):
    return {"game_id": game, "event_type": kind, "event_owner_team_id": owner, "zone_code": zone,
            "situation_code": code, "winning_player_id": winner, "losing_player_id": loser}


def test_each_faceoff_is_a_win_for_one_skater_and_a_loss_for_the_other_with_the_zone_flipped():
    totals, played, skipped = f.count_faceoffs([faceoff(1, 2, zone="O")], GAMES)
    assert totals[(1, 10, "all")]["faceoff_wins"] == 1 and totals[(1, 10, "oz")]["faceoffs"] == 1
    assert totals[(2, 20, "all")]["faceoff_losses"] == 1 and totals[(2, 20, "dz")]["faceoffs"] == 1
    assert (2, 20, "oz") not in totals and (1, 10, "dz") not in totals
    assert played == {(1, 10): 1, (2, 20): 1} and skipped == 0


def test_strength_is_each_skaters_own_team_from_the_situation_code():
    # code 1451: away goalie 1, away skaters 4, home skaters 5, home goalie 1 -> home power play
    totals, _, _ = f.count_faceoffs([faceoff(1, 2, owner=10, code="1451")], GAMES)
    assert totals[(1, 10, "pp")]["faceoffs"] == 1 and totals[(2, 20, "sh")]["faceoffs"] == 1
    totals, _, _ = f.count_faceoffs([faceoff(3, 4, owner=20, code="1451")], GAMES)  # the away team wins
    assert totals[(3, 20, "sh")]["faceoffs"] == 1 and totals[(4, 10, "pp")]["faceoffs"] == 1


def test_neutral_zone_stays_neutral_and_events_without_a_code_or_zone_count_only_where_known():
    totals, _, _ = f.count_faceoffs([faceoff(1, 2, zone="N", code=None), faceoff(1, 2, zone=None)], GAMES)
    assert totals[(1, 10, "nz")]["faceoffs"] == 1 and totals[(2, 20, "nz")]["faceoffs"] == 1
    assert totals[(1, 10, "all")]["faceoffs"] == 2 and totals[(1, 10, "ev")]["faceoffs"] == 1


def test_other_events_and_unusable_faceoffs_are_skipped():
    events = [faceoff(1, 2, kind="shot-on-goal"), faceoff(None, 2), faceoff(1, 2, owner=99), faceoff(1, 2, game=5)]
    totals, played, skipped = f.count_faceoffs(events, GAMES)
    assert not totals and not played and skipped == 3


def test_rates():
    assert f.add_faceoff_rates({"faceoffs": 4, "faceoff_wins": 3})["faceoff_pct"] == 75.0
    assert f.add_faceoff_rates({"faceoffs": 0, "faceoff_wins": 0})["faceoff_pct"] is None


def test_check_helpers():
    assert c.percent_scale([0.5, None, 0.62]) == 100 and c.percent_scale([55.0, 40.0]) == 1
    rows = [{"kind": "team", "player_id": 1, "situation": "all", "faceoffs": 6, "faceoff_wins": 3},
            {"kind": "team", "player_id": 1, "situation": "all", "faceoffs": 4, "faceoff_wins": 3},
            {"kind": "total", "player_id": 1, "situation": "all", "faceoffs": 10, "faceoff_wins": 6}]
    totals = c.our_totals(rows)
    assert totals[(1, "all")] == [10, 6]
    report = [{"playerId": 1, "totalFaceoffs": 10, "faceoffWinPct": 0.6},
              {"playerId": 2, "totalFaceoffs": 0, "faceoffWinPct": None}]
    n, exact, mine, theirs, worst, both, within, worst_pct = c.compare(totals, report, "all")
    assert (n, exact, mine, theirs, worst, both, within) == (2, 2, 10, 10, 0, 1, 1) and abs(worst_pct) < 1e-9