"""Tests for the team power-play and penalty-kill logic. Made-up games, no real data."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform"))

import team_special_teams as t  # noqa: E402

GAMES = {1: {"home_team_id": 1, "away_team_id": 2}, 2: {"home_team_id": 2, "away_team_id": 3}}


def penalty(team, second, minutes=2, game=1, period="REG"):
    return {"game_id": game, "event_type": "penalty", "period_type": period, "game_seconds": second,
            "event_owner_team_id": team, "penalty_minutes": minutes}


def prepared(*events, extra=()):
    return t.prepare_penalties(list(events) + list(extra), GAMES)


def goal(team, sf, sa, gf=1, ga=1, game=1):
    return {"attempt_type": "goal", "game_id": game, "team_id": team, "skaters_for": sf, "skaters_against": sa,
            "goalie_for": gf, "goalie_against": ga}


def test_prepare_adds_the_opponent_and_whether_the_game_went_to_overtime():
    rows = prepared(penalty(1, 100), penalty(3, 200, game=2), extra=[
        {"game_id": 2, "event_type": "period-start", "period_type": "OT", "game_seconds": 3600,
         "event_owner_team_id": None, "penalty_minutes": None}])
    assert [(r["opponent_team_id"], r["game_has_ot"]) for r in rows] == [(2, False), (2, True)]


def test_each_minor_or_major_is_one_opportunity_and_a_double_minor_two():
    opp, short = t.penalty_opportunities(prepared(penalty(1, 100), penalty(1, 500, 5), penalty(2, 900, 4)))
    assert opp[(1, 2)] == 2 and opp[(1, 1)] == 2
    assert short[(1, 1)] == 2 and short[(1, 2)] == 2


def test_misconducts_and_penalty_shots_give_no_power_play():
    opp, _ = t.penalty_opportunities(prepared(penalty(1, 100, 10), penalty(1, 200, 0), penalty(1, 300, None)))
    assert not opp


def test_same_length_penalties_at_one_second_cancel_and_a_double_minor_leaves_one_minor():
    opp, _ = t.penalty_opportunities(prepared(penalty(1, 100), penalty(2, 100)))
    assert not opp
    opp, _ = t.penalty_opportunities(prepared(penalty(1, 100, 5), penalty(2, 100, 5)))  # a fight
    assert not opp
    opp, _ = t.penalty_opportunities(prepared(penalty(1, 100, 4), penalty(2, 100, 2)))
    assert opp[(1, 2)] == 1 and opp[(1, 1)] == 0
    opp, _ = t.penalty_opportunities(prepared(penalty(1, 100, 2), penalty(2, 100, 5)))  # different lengths: no offset
    assert opp[(1, 1)] == 1 and opp[(1, 2)] == 1


def test_penalties_at_the_end_of_regulation_count_only_when_there_is_overtime():
    opp, _ = t.penalty_opportunities(prepared(penalty(1, 3600)))
    assert not opp
    ot = {"game_id": 1, "event_type": "period-start", "period_type": "OT", "game_seconds": 3600,
          "event_owner_team_id": None, "penalty_minutes": None}
    opp, _ = t.penalty_opportunities(prepared(penalty(1, 3600), extra=[ot]))
    assert opp[(1, 2)] == 1
    opp, _ = t.penalty_opportunities(prepared(penalty(1, 3000)))
    assert opp[(1, 2)] == 1


def test_goals_by_strength_uses_the_situation_code_and_skips_even_strength():
    goals = t.goals_by_strength([goal(1, 5, 4), goal(2, 4, 5), goal(1, 5, 5), goal(1, 6, 5, gf=0),
                                 {**goal(1, 5, 4), "attempt_type": "shot-on-goal"}])
    assert goals[(1, 1)]["pp"] == 1 and goals[(1, 2)]["sh"] == 1 and goals[(1, 1)]["sh"] == 0
    assert (1, 1) in goals and sum(goals[(1, 1)].values()) == 1


def test_game_rows_cover_every_team_and_game_with_goals_for_and_against():
    penalties = prepared(penalty(2, 100), penalty(2, 400), penalty(1, 800))
    attempts = [goal(1, 5, 4), goal(2, 4, 5)]  # team 1 scores on the power play, team 2 shorthanded
    rows = {(r["game_id"], r["team_id"]): r for r in t.build_team_game_rows(GAMES, penalties, attempts)}
    assert len(rows) == 4
    one, two = rows[(1, 1)], rows[(1, 2)]
    assert (one["pp_opportunities"], one["pp_goals"], one["times_shorthanded"], one["pk_goals_against"]) == (2, 1, 1, 0)
    assert (one["sh_goals_for"], one["sh_goals_against"], one["opponent_team_id"]) == (0, 1, 2)
    assert (two["pp_opportunities"], two["pp_goals"], two["times_shorthanded"], two["pk_goals_against"]) == (1, 0, 2, 1)
    assert (two["sh_goals_for"], two["sh_goals_against"]) == (1, 0)
    assert rows[(2, 3)]["pp_opportunities"] == 0


def test_season_rows_add_up_and_give_percentages():
    rows = [
        {"game_id": 1, "team_id": 1, "pp_opportunities": 4, "pp_goals": 1, "times_shorthanded": 2,
         "pk_goals_against": 1, "sh_goals_for": 0, "sh_goals_against": 0},
        {"game_id": 2, "team_id": 1, "pp_opportunities": 4, "pp_goals": 1, "times_shorthanded": 2,
         "pk_goals_against": 0, "sh_goals_for": 1, "sh_goals_against": 0},
        {"game_id": 3, "team_id": 2, "pp_opportunities": 0, "pp_goals": 0, "times_shorthanded": 0,
         "pk_goals_against": 0, "sh_goals_for": 0, "sh_goals_against": 0},
    ]
    one, two = t.build_team_season_rows(rows, {1: "AAA"})
    assert (one["team"], one["games_played"], one["pp_opportunities"], one["pp_goals"]) == ("AAA", 2, 8, 2)
    assert one["pp_pct"] == pytest.approx(25.0) and one["pk_pct"] == pytest.approx(75.0)
    assert one["pp_opportunities_per_game"] == 4 and one["times_shorthanded_per_game"] == 2
    assert two["team"] == "2" and two["pp_pct"] is None and two["pk_pct"] is None


def event(code, team=1, second=2257, period="REG", kind="goal", game=1):
    return {"game_id": game, "event_type": kind, "period_type": period, "game_seconds": second,
            "event_owner_team_id": team, "situation_code": code}


def test_penalty_shot_goals_are_found_from_the_situation_code_for_either_side():
    events = [event("1010", team=1), event("1010", team=2), event("0101", team=2), event("1551"),
              event("1010", period="SO"), event("1010", kind="shot-on-goal"), event(None)]
    shots = t.penalty_shot_goals(events, GAMES)
    # team 1 is home: 1010 = away goalie 1, away skaters 0, home skaters 1, home goalie 0 -> home shot.
    # For team 2 (away) 0101 is the away shot, while 1010 is not a shot for the away team.
    assert [(s["team_id"], s["is_home"]) for s in shots] == [(1, True), (2, False)]


def test_stint_strength_uses_the_stint_that_ends_on_the_second():
    stints = [{"start_game_seconds": 0, "end_game_seconds": 100, "home_strength": "ev", "away_strength": "ev"},
              {"start_game_seconds": 100, "end_game_seconds": 200, "home_strength": "sh", "away_strength": "pp"}]
    assert t.stint_strength(stints, 100, True) == "ev"
    assert t.stint_strength(stints, 101, True) == "sh" and t.stint_strength(stints, 101, False) == "pp"
    assert t.stint_strength(stints, 500, True) is None


def test_only_shorthanded_penalty_shot_goals_are_added_to_shorthanded_goals():
    stints = {1: [{"start_game_seconds": 0, "end_game_seconds": 300, "home_strength": "sh", "away_strength": "pp"},
                  {"start_game_seconds": 300, "end_game_seconds": 600, "home_strength": "pp", "away_strength": "sh"}]}
    shots = [{"game_id": 1, "game_seconds": 100, "team_id": 1, "is_home": True},   # home shorthanded: counts
             {"game_id": 1, "game_seconds": 400, "team_id": 1, "is_home": True}]   # home on the power play: does not
    counts = t.shorthanded_penalty_shot_goals(shots, stints)
    assert counts == {(1, 1): 1}
    rows = {(r["game_id"], r["team_id"]): r for r in t.build_team_game_rows(GAMES, [], [], counts)}
    assert (rows[(1, 1)]["sh_goals_for"], rows[(1, 2)]["sh_goals_against"]) == (1, 1)
    assert rows[(1, 1)]["pp_goals"] == 0


def test_parquet_round_trip(tmp_path):
    import build_team_special_teams as b
    import pyarrow.parquet as pq

    game_rows = t.build_team_game_rows(GAMES, prepared(penalty(2, 100)), [goal(1, 5, 4)])
    season_rows = t.build_team_season_rows(game_rows, {1: "AAA", 2: "BBB", 3: "CCC"})
    for row in game_rows + season_rows:
        row["season"] = 2025
    b.write_table(tmp_path / "g.parquet", game_rows, b.GAME_SCHEMA)
    b.write_table(tmp_path / "s.parquet", season_rows, b.SEASON_SCHEMA)
    assert pq.read_table(tmp_path / "g.parquet").num_rows == 4
    table = pq.read_table(tmp_path / "s.parquet")
    assert table.column_names == b.SEASON_SCHEMA.names and table.num_rows == 3