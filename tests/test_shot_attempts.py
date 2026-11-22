"""Tests for the Phase 4.1 shot-attempt logic. A tiny made-up game, no real data.

Teams: home = 1, away = 2. Home players 11-15 (skaters), away players 21-25.
The home team defends the left side, so home attacks right (+x) and away attacks left.
"""

import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform"))

import build_shot_attempts  # noqa: E402
import shot_attempts  # noqa: E402

GAME = {"game_id": 1, "home_team_id": 1, "away_team_id": 2}


def event(event_id, event_type, owner, code="1551", period_type="REG", **extra):
    row = {
        "game_id": 1,
        "event_id": event_id,
        "sort_order": event_id,
        "period": 1,
        "period_type": period_type,
        "seconds_in_period": event_id * 10,
        "game_seconds": event_id * 10,
        "event_type": event_type,
        "situation_code": code,
        "event_owner_team_id": owner,
        "x_coord": None,
        "y_coord": None,
        "zone_code": None,
        "shot_type": None,
        "shooting_player_id": None,
        "scoring_player_id": None,
        "goalie_in_net_id": None,
        "blocking_player_id": None,
        "home_defending_side": "left",
    }
    row.update(extra)
    return row


def on_ice_row(event_id, matches=True):
    return {
        "event_id": event_id,
        "home_skater_ids": [11, 12, 13, 14, 15],
        "away_skater_ids": [21, 22, 23, 24, 25],
        "matches_situation": matches,
        "uses_conflicting_shift": False,
    }


def build(events, on_ice=None):
    return shot_attempts.build_game_shot_attempts(GAME, events, on_ice or {})


def test_only_attempt_events_are_kept_and_shooter_comes_from_the_right_field():
    rows = build(
        [
            event(1, "hit", 1),
            event(2, "shot-on-goal", 1, shooting_player_id=11),
            event(3, "goal", 2, scoring_player_id=21),
            event(4, "failed-shot-attempt", 1, shooting_player_id=11),
        ]
    )
    assert [(r["attempt_type"], r["shooter_id"]) for r in rows] == [
        ("shot-on-goal", 11),
        ("goal", 21),
    ]


def test_shootout_events_are_left_out():
    rows = build([event(1, "shot-on-goal", 1, period_type="SO", shooting_player_id=11)])
    assert rows == []


def test_penalty_shot_is_left_out_but_its_goal_still_counts_in_the_score():
    rows = build(
        [
            event(1, "goal", 1, code="1010", scoring_player_id=11),
            event(2, "shot-on-goal", 2, shooting_player_id=21),
        ]
    )
    assert len(rows) == 1
    assert (rows[0]["score_for"], rows[0]["score_against"]) == (0, 1)


def test_score_is_before_the_attempt_and_from_the_shooting_teams_view():
    rows = build(
        [
            event(1, "goal", 1, scoring_player_id=11),
            event(2, "goal", 1, scoring_player_id=12),
            event(3, "shot-on-goal", 2, shooting_player_id=21),
            event(4, "goal", 2, scoring_player_id=22),
        ]
    )
    assert [(r["score_for"], r["score_against"]) for r in rows] == [(0, 0), (1, 0), (0, 2), (0, 2)]


def test_coordinates_are_turned_so_the_shooting_team_attacks_positive_x():
    rows = build(
        [
            event(1, "shot-on-goal", 1, shooting_player_id=11, x_coord=70.0, y_coord=5.0),
            event(2, "shot-on-goal", 2, shooting_player_id=21, x_coord=-70.0, y_coord=-5.0),
            event(3, "shot-on-goal", 1, shooting_player_id=11, x_coord=70.0, y_coord=5.0, home_defending_side="right"),
            event(4, "shot-on-goal", 1, shooting_player_id=11, x_coord=70.0, y_coord=5.0, home_defending_side=None),
        ]
    )
    assert [(r["x"], r["y"]) for r in rows] == [(70.0, 5.0), (70.0, 5.0), (-70.0, -5.0), (None, None)]
    assert (rows[0]["x_raw"], rows[0]["y_raw"]) == (70.0, 5.0)


def test_strength_is_from_the_shooting_teams_view():
    rows = build(
        [
            event(1, "shot-on-goal", 1, code="1541", shooting_player_id=11),  # away 5, home 4
            event(2, "shot-on-goal", 2, code="1541", shooting_player_id=21),
            event(3, "shot-on-goal", 1, code="0651", shooting_player_id=11),  # away goalie pulled
        ]
    )
    assert [(r["skaters_for"], r["skaters_against"], r["goalie_for"], r["goalie_against"]) for r in rows] == [
        (4, 5, 1, 1),
        (5, 4, 1, 1),
        (5, 6, 1, 0),
    ]


def test_missing_situation_code_gives_null_strength():
    rows = build([event(1, "shot-on-goal", 1, code=None, shooting_player_id=11)])
    assert rows[0]["skaters_for"] is None and rows[0]["goalie_against"] is None


def test_on_ice_lists_are_from_the_shooting_teams_view_and_games_without_shifts_keep_rows():
    events = [event(1, "shot-on-goal", 2, shooting_player_id=21)]
    with_shifts = build(events, {1: on_ice_row(1)})[0]
    assert with_shifts["skater_ids_for"] == [21, 22, 23, 24, 25]
    assert with_shifts["skater_ids_against"] == [11, 12, 13, 14, 15]
    assert with_shifts["has_on_ice"] is True
    without = build(events)[0]
    assert without["has_on_ice"] is False and without["skater_ids_for"] is None


def test_blocker_on_the_shooters_team_is_marked():
    events = [
        event(1, "blocked-shot", 1, shooting_player_id=11, blocking_player_id=21),
        event(2, "blocked-shot", 1, shooting_player_id=11, blocking_player_id=12),
        event(3, "blocked-shot", 1, shooting_player_id=11, blocking_player_id=99),
        event(4, "shot-on-goal", 1, shooting_player_id=11),
    ]
    rows = build(events, {e["event_id"]: on_ice_row(e["event_id"]) for e in events})
    assert [r["blocker_is_teammate"] for r in rows] == [False, True, None, None]


def test_parquet_round_trip(tmp_path):
    events = [event(1, "shot-on-goal", 1, shooting_player_id=11, x_coord=70.0, y_coord=5.0)]
    rows = build(events, {1: on_ice_row(1)})
    rows[0]["season"] = 2025
    path = tmp_path / "shot_attempts.parquet"
    build_shot_attempts.write_table(path, rows)
    table = pq.read_table(path)
    assert table.column_names == [name for name, _ in build_shot_attempts.SCHEMA]
    assert table.column("skater_ids_for").to_pylist()[0] == [11, 12, 13, 14, 15]
