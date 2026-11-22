"""Tests for the Phase 4.4 event-stat logic. A tiny made-up game, no real data.

Teams: home = 1 (goalie 10, skaters 11-15), away = 2 (goalie 40, skaters 21-25).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform"))

import base_tables  # noqa: E402
import stints  # noqa: E402

GAME = {"game_id": 1, "home_team_id": 1, "away_team_id": 2}


def shift(player, team, start, end, goalie=False):
    return {
        "game_id": 1,
        "player_id": player,
        "team_id": team,
        "period": 1,
        "start_game_seconds": start,
        "end_game_seconds": end,
        "is_goalie": goalie,
    }


def ice(start, end, home=range(11, 16), away=range(21, 26)):
    rows = [shift(10, 1, start, end, True), shift(40, 2, start, end, True)]
    rows += [shift(p, 1, start, end) for p in home]
    rows += [shift(p, 2, start, end) for p in away]
    return rows


def event(event_type, time, owner, period_type="REG", **fields):
    row = {
        "event_type": event_type,
        "game_seconds": time,
        "event_owner_team_id": owner,
        "period_type": period_type,
    }
    row.update(fields)
    return row


def tables(shift_rows, events):
    players, _, notes = base_tables.build_game_tables(
        GAME, stints.stint_rows(GAME, stints.build_stints(GAME, shift_rows)), [], events
    )
    return players, notes


def find(rows, **wanted):
    found = [r for r in rows if all(r[k] == v for k, v in wanted.items())]
    assert len(found) == 1, found
    return found[0]


def test_assists_are_credited_to_the_players_named_on_the_goal():
    players, notes = tables(
        ice(0, 60), [event("goal", 30, 1, assist1_player_id=12, assist2_player_id=13, scoring_player_id=11)]
    )
    assert find(players, player_id=12)["assists_primary"] == 1
    assert find(players, player_id=13)["assists_secondary"] == 1
    assert find(players, player_id=12)["assists_secondary"] == 0
    assert notes["goal:team_differs_from_owner"] == 0


def test_goal_events_use_the_end_inclusive_rule():
    rows = ice(0, 60) + ice(60, 120, home=range(16, 21), away=range(26, 31))
    players, _ = tables(rows, [event("goal", 60, 1, assist1_player_id=11), event("hit", 60, 1, hitting_player_id=16)])
    assert find(players, player_id=11)["assists_primary"] == 1  # the stint that ends at 60
    assert find(players, player_id=16)["hits_made"] == 1  # a hit belongs to the stint that starts at 60


def test_hits_credit_the_hitter_and_the_player_hit_each_in_his_own_team():
    players, notes = tables(ice(0, 60), [event("hit", 30, 1, hitting_player_id=11, hittee_player_id=21)])
    assert find(players, player_id=11)["hits_made"] == 1
    assert find(players, player_id=21)["hits_taken"] == 1
    assert find(players, player_id=21)["hits_made"] == 0
    assert notes["hits_made:team_matches_owner"] == 1 and notes["hits_taken:team_matches_owner"] == 1


def test_giveaways_takeaways_and_faceoffs():
    events = [
        event("giveaway", 10, 2, player_id=21),
        event("takeaway", 20, 1, player_id=12),
        event("faceoff", 30, 1, winning_player_id=13, losing_player_id=22),
    ]
    players, _ = tables(ice(0, 60), events)
    assert find(players, player_id=21)["giveaways"] == 1
    assert find(players, player_id=12)["takeaways"] == 1
    assert find(players, player_id=13)["faceoff_wins"] == 1
    assert find(players, player_id=22)["faceoff_losses"] == 1


def test_penalties_taken_drawn_and_minutes_and_a_bench_penalty_counts_for_nobody():
    events = [
        event("penalty", 10, 1, committed_by_player_id=11, drawn_by_player_id=21, penalty_minutes=2),
        event("penalty", 20, 2, committed_by_player_id=22, drawn_by_player_id=12, penalty_minutes=5),
        event("penalty", 30, 1, committed_by_player_id=None, drawn_by_player_id=23, penalty_minutes=2),
    ]
    players, _ = tables(ice(0, 60), events)
    taker = find(players, player_id=11)
    assert (taker["penalties_taken"], taker["penalty_minutes"], taker["penalties_drawn"]) == (1, 2, 0)
    assert find(players, player_id=21)["penalties_drawn"] == 1
    assert find(players, player_id=22)["penalty_minutes"] == 5
    assert find(players, player_id=23)["penalties_drawn"] == 1  # drawn by him even when the minor was a bench minor
    assert all(r["penalty_minutes"] == 0 for r in players if r["player_id"] not in (11, 22))


def test_penalties_use_the_end_inclusive_rule():
    rows = ice(0, 60) + ice(60, 120, home=range(16, 21), away=range(26, 31))
    players, _ = tables(rows, [event("penalty", 60, 1, committed_by_player_id=11, penalty_minutes=2)])
    assert find(players, player_id=11)["penalties_taken"] == 1


def test_stats_land_in_the_state_of_the_players_own_team():
    players, _ = tables(
        ice(0, 60, home=range(11, 15)), [event("hit", 30, 2, hitting_player_id=21, hittee_player_id=11)]
    )
    assert find(players, player_id=21, strength="pp")["hits_made"] == 1
    assert find(players, player_id=11, strength="sh")["hits_taken"] == 1


def test_goalie_events_and_shootout_events_are_not_credited_to_skater_rows():
    events = [
        event("giveaway", 10, 1, player_id=10),
        event("giveaway", 20, 1, player_id=11, period_type="SO"),
    ]
    players, notes = tables(ice(0, 60), events)
    assert notes["goalie_event"] == 1
    assert all(r["player_id"] != 10 for r in players)
    assert find(players, player_id=11)["giveaways"] == 0


def test_a_player_off_the_ice_is_credited_on_the_side_the_owner_team_implies():
    players, notes = tables(ice(0, 60), [event("hit", 30, 1, hitting_player_id=99, hittee_player_id=98)])
    assert find(players, player_id=99)["hits_made"] == 1 and find(players, player_id=99)["team_id"] == 1
    assert find(players, player_id=98)["hits_taken"] == 1 and find(players, player_id=98)["team_id"] == 2
    assert notes["actor_not_on_ice"] == 2


def test_a_player_whose_team_differs_from_the_owner_is_counted_in_the_notes():
    _, notes = tables(ice(0, 60), [event("takeaway", 30, 2, player_id=11)])  # owner says away, he is home
    assert notes["takeaways:team_differs_from_owner"] == 1


def test_events_outside_every_stint_are_counted_and_other_event_types_ignored():
    players, notes = tables(ice(0, 60), [event("hit", 500, 1, hitting_player_id=11), event("stoppage", 30, 1)])
    assert notes["events_outside_stints"] == 1
    assert all(r["hits_made"] == 0 for r in players)
