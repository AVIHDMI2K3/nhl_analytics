"""Tests for the boxscore-versus-play-by-play diagnosis. A tiny made-up game, no real data.

Home team 1 (goalie 10, skaters 11-15), away team 2 (goalie 40, skaters 21-25).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform"))

import diagnose_boxscore_vs_pbp as diag  # noqa: E402
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


def stint_rows(home_goalie_off_from=None, home_goalie=10):
    rows = [shift(40, 2, 0, 100, True)] + [shift(p, 2, 0, 100) for p in range(21, 26)]
    rows += [shift(p, 1, 0, 100) for p in range(11, 16)]
    if home_goalie_off_from is None:
        rows.append(shift(home_goalie, 1, 0, 100, True))
    else:
        rows.append(shift(home_goalie, 1, 0, home_goalie_off_from, True))
        rows.append(shift(16, 1, home_goalie_off_from, 100))
    return stints.stint_rows(GAME, stints.build_stints(GAME, rows))


def event(
    time,
    owner,
    shooter,
    goalie,
    kind="shot-on-goal",
    period_type="REG",
    shot_type="wrist",
    remaining=900,
    event_id=None,
):
    return {
        "game_id": 1,
        "event_id": event_id or time,
        "event_type": kind,
        "period": 1,
        "period_type": period_type,
        "game_seconds": time,
        "seconds_remaining_in_period": remaining,
        "event_owner_team_id": owner,
        "shooting_player_id": None if kind == "goal" else shooter,
        "scoring_player_id": shooter if kind == "goal" else None,
        "goalie_in_net_id": goalie,
        "shot_type": shot_type,
        "x_coord": 10.0,
        "y_coord": 5.0,
    }


def box(team, player, group, **numbers):
    return {"team_id": team, "player_id": player, "player_group": group, "sog": 0, "shots_against": 0, **numbers}


def test_annotate_flags_duplicates_rebounds_and_odd_events():
    events = [
        event(10, 2, 21, 10),
        event(11, 2, 21, 10),  # a shot and another by him 1 s later
        event(50, 2, 22, 10, kind="goal"),  # a goal
        event(60, 2, 23, 10, shot_type=None, period_type="OT", remaining=5),
        event(70, 2, 40, None),  # the goalie shoots at an empty net
        event(80, 2, 21, 40),  # a named goalie on the shooter's own team
    ]
    rows = {r["event"]["game_seconds"]: r for r in diag.annotate(events, {10: 1, 40: 2})}
    assert rows[10]["duplicate_within_2s"] and rows[11]["duplicate_within_2s"] and not rows[60]["duplicate_within_2s"]
    assert rows[50]["within_1s_after_goal"] is False  # the goal does not count itself
    assert (
        not rows[10]["no_shot_type"]
        and rows[60]["no_shot_type"]
        and rows[60]["overtime"]
        and rows[60]["last_10s_of_period"]
    )
    assert rows[70]["shooter_is_goalie"] and not rows[10]["shooter_is_goalie"]
    assert rows[80]["goalie_on_shooters_team"] and not rows[10]["goalie_on_shooters_team"]


def test_a_shot_within_a_second_after_a_goal_is_flagged():
    rows = {
        r["event"]["event_id"]: r
        for r in diag.annotate(
            [event(50, 2, 22, 10, kind="goal", event_id=1), event(51, 1, 11, 40, event_id=2)], {10: 1, 40: 2}
        )
    }
    assert rows[2]["within_1s_after_goal"] and not rows[1]["within_1s_after_goal"]


def test_goalie_shift_status():
    events = [event(10, 2, 21, 10), event(80, 2, 21, 10), event(85, 2, 21, 99)]
    statuses = {r["game_seconds"]: r["status"] for r in diag.goalie_shift_status(GAME, events, stint_rows(60))}
    assert statuses == {10: "named goalie on the ice", 80: "no goalie on the ice", 85: "no goalie on the ice"}
    statuses = {
        r["game_seconds"]: r["status"] for r in diag.goalie_shift_status(GAME, [event(10, 2, 21, 99)], stint_rows())
    }
    assert statuses == {10: "a different goalie on the ice"}
    assert (
        diag.goalie_shift_status(GAME, [event(10, 2, 21, None)], stint_rows()) == []
    )  # no goalie named: nothing to check


def test_compare_counts_lists_only_differences():
    assert diag.compare_counts({1: 3, 2: 1}, {1: 3, 2: 2, 3: 1}) == [(2, 2, 1), (3, 1, 0)]


def test_process_game_splits_events_and_finds_differences():
    events = [event(10, 2, 21, 10), event(11, 2, 21, 10), event(20, 2, 22, 10), event(70, 2, 40, None)]
    boxes = [
        box(2, 21, "forwards", sog=1),
        box(2, 22, "forwards", sog=1),
        box(2, 40, "goalies"),
        box(1, 10, "goalies", shots_against=3),
    ]
    result = diag.process_game(GAME, events, stint_rows(), boxes)
    assert result["reconcile"]["events"] == 4 and result["reconcile"]["by_goalies"] == 1
    assert result["reconcile"]["box_skater_shots"] == 2
    assert [(p, b, e) for _, p, b, e, _ in result["skater_diffs"]] == [(21, 1, 2)]
    assert [(p, b, e) for _, p, b, e, _ in result["goalie_diffs"]] == []  # goalie 10 faced three shots named for him
    assert len(result["skater_agree"]) == 1 and result["shift_results"]
