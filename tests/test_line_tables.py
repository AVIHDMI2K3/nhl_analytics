"""Tests for src/nhl_pipeline/transform/line_tables.py. A made-up game: home team 1, away team 2.

Home forwards 1-3 and defense 4-5; away forwards 11-13 and defense 14-15. Home forward 6 and defenseman 7 are
extra players for line changes.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))

import line_tables as lt  # noqa: E402

GAME = {"game_id": 1, "home_team_id": 1, "away_team_id": 2}
POSITIONS = {1: "F", 2: "F", 3: "F", 4: "D", 5: "D", 6: "F", 7: "D", 11: "F", 12: "F", 13: "F", 14: "D", 15: "D"}


def stint(
    start,
    end,
    home=(1, 2, 3, 4, 5),
    away=(11, 12, 13, 14, 15),
    home_goalies=(30,),
    away_goalies=(40,),
    home_strength="ev",
    away_strength="ev",
):
    return {
        "start_game_seconds": start,
        "end_game_seconds": end,
        "seconds": end - start,
        "home_skater_ids": list(home),
        "away_skater_ids": list(away),
        "home_goalie_ids": list(home_goalies),
        "away_goalie_ids": list(away_goalies),
        "home_strength": home_strength,
        "away_strength": away_strength,
    }


def attempt(kind, time, home=True, **extra):
    return {"attempt_type": kind, "game_seconds": time, "is_home": home, **extra}


def find(rows, team_id, unit_type, player_ids):
    found = [
        r for r in rows if (r["team_id"], r["unit_type"], r["player_ids"]) == (team_id, unit_type, list(player_ids))
    ]
    assert len(found) == 1
    return found[0]


def test_seconds_and_attempts_go_to_the_line_and_pair_on_the_ice():
    rows = lt.build_game_unit_rows(
        GAME, [stint(0, 60)], [attempt("shot-on-goal", 30), attempt("blocked-shot", 40, home=False)], POSITIONS
    )
    home_line, home_pair = find(rows, 1, "line", (1, 2, 3)), find(rows, 1, "pair", (4, 5))
    assert home_line["seconds"] == 60 and home_pair["seconds"] == 60
    assert home_line["for_sog"] == 1 and home_pair["for_sog"] == 1
    assert home_line["against_block"] == 1 and find(rows, 2, "line", (11, 12, 13))["for_block"] == 1
    assert find(rows, 2, "pair", (14, 15))["against_sog"] == 1


def test_a_line_change_starts_a_new_unit_and_the_pair_carries_on():
    rows = lt.build_game_unit_rows(GAME, [stint(0, 60), stint(60, 100, home=(6, 2, 3, 4, 5))], [], POSITIONS)
    assert find(rows, 1, "line", (1, 2, 3))["seconds"] == 60 and find(rows, 1, "line", (2, 3, 6))["seconds"] == 40
    assert find(rows, 1, "pair", (4, 5))["seconds"] == 100


def test_only_five_on_five_counts():
    power_play = stint(0, 60, away=(11, 12, 13, 14), home_strength="pp", away_strength="sh")
    empty_net = stint(60, 90, home_goalies=())
    rows = lt.build_game_unit_rows(GAME, [power_play, empty_net], [attempt("shot-on-goal", 30)], POSITIONS)
    assert rows == []


def test_the_attempts_state_comes_from_the_situation_code_when_it_has_one():
    # the stint says 5v5 but the code says the home team is on a power play: the attempt is not a 5v5 attempt
    coded = attempt("goal", 30, skaters_for=5, skaters_against=4, goalie_for=1, goalie_against=1)
    rows = lt.build_game_unit_rows(GAME, [stint(0, 60)], [coded], POSITIONS)
    assert find(rows, 1, "line", (1, 2, 3))["seconds"] == 60 and find(rows, 1, "line", (1, 2, 3))["for_goal"] == 0


def test_a_stint_without_three_forwards_has_no_line():
    four_forwards = stint(0, 60, home=(1, 2, 3, 6, 4))
    rows = lt.build_game_unit_rows(GAME, [four_forwards], [], POSITIONS)
    assert [r for r in rows if r["team_id"] == 1] == []


def test_a_shot_on_goal_at_a_line_change_is_credited_to_the_outgoing_unit():
    # shot on goal at second 60: skaters from the stint ending at 60 (same rule as the base tables)
    stints = [stint(0, 60), stint(60, 100, home=(6, 2, 3, 4, 5))]
    rows = lt.build_game_unit_rows(GAME, stints, [attempt("shot-on-goal", 60)], POSITIONS)
    assert find(rows, 1, "line", (1, 2, 3))["for_sog"] == 1 and find(rows, 1, "line", (2, 3, 6))["for_sog"] == 0


def test_season_rows_sum_the_games_and_work_out_the_rates():
    game = [
        {
            "game_id": 1,
            "team_id": 1,
            "unit_type": "line",
            "player_ids": [1, 2, 3],
            "seconds": 1800,
            "for_goal": 1,
            "for_sog": 5,
            "for_miss": 2,
            "for_block": 2,
            "against_goal": 0,
            "against_sog": 3,
            "against_miss": 1,
            "against_block": 1,
        },
        {
            "game_id": 2,
            "team_id": 1,
            "unit_type": "line",
            "player_ids": [1, 2, 3],
            "seconds": 1800,
            "for_goal": 0,
            "for_sog": 3,
            "for_miss": 1,
            "for_block": 0,
            "against_goal": 1,
            "against_sog": 4,
            "against_miss": 0,
            "against_block": 0,
        },
        {
            "game_id": 3,
            "team_id": 1,
            "unit_type": "line",
            "player_ids": [1, 2, 3],
            "seconds": 0,
            "for_goal": 0,
            "for_sog": 0,
            "for_miss": 0,
            "for_block": 0,
            "against_goal": 0,
            "against_sog": 0,
            "against_miss": 0,
            "against_block": 0,
        },
    ]
    (row,) = lt.season_unit_rows(game)
    assert row["games"] == 2 and row["seconds"] == 3600
    assert (row["cf"], row["ca"], row["ff"], row["fa"], row["sf"], row["sa"], row["gf"], row["ga"]) == (
        14,
        10,
        12,
        9,
        9,
        8,
        1,
        1,
    )
    assert round(row["cf_pct"], 2) == 58.33 and row["cf_per_60"] == 14 and row["ga_per_60"] == 1
    assert round(row["sh_pct"], 2) == round(100 / 9, 2) and round(row["sv_pct"], 2) == 87.5
    assert round(row["pdo"], 2) == round(100 / 9 + 87.5, 2)


def test_rates_are_empty_when_the_divisor_is_zero():
    empty = {
        "game_id": 1,
        "team_id": 1,
        "unit_type": "pair",
        "player_ids": [4, 5],
        "seconds": 60,
        "for_goal": 0,
        "for_sog": 0,
        "for_miss": 0,
        "for_block": 0,
        "against_goal": 0,
        "against_sog": 0,
        "against_miss": 0,
        "against_block": 0,
    }
    (row,) = lt.season_unit_rows([empty])
    assert row["cf_pct"] is None and row["sh_pct"] is None and row["pdo"] is None and row["cf_per_60"] == 0


def test_the_time_together_is_summarized_by_unit_type():
    rows = [{"team_id": 1, "unit_type": "line", "seconds": m * 60} for m in (10, 40, 70, 120)]
    rows += [
        {"team_id": 2, "unit_type": "line", "seconds": 65 * 60},
        {"team_id": 1, "unit_type": "pair", "seconds": 600},
    ]
    summary = lt.describe_units(rows)
    assert summary["line"]["units"] == 5 and summary["line"]["median"] == 65 and summary["line"]["max"] == 120
    assert summary["line"]["at_least"] == {30: 4, 60: 3, 100: 1} and summary["line"]["per_team"][60] == 1.5
    assert summary["pair"]["units"] == 1 and summary["pair"]["at_least"][30] == 0


def test_positions_come_from_the_boxscore_position_or_group_and_goalies_are_left_out():
    rows = [
        {"game_id": 1, "player_id": 1, "position": "C", "player_group": "forwards"},
        {"game_id": 1, "player_id": 2, "position": "L", "player_group": None},
        {"game_id": 1, "player_id": 3, "position": None, "player_group": "defense"},
        {"game_id": 1, "player_id": 4, "position": "D", "player_group": "defense"},
        {"game_id": 1, "player_id": 5, "position": "G", "player_group": "goalies"},
        {"game_id": 2, "player_id": 1, "position": "R", "player_group": "forwards"},
    ]
    assert lt.positions_by_game(rows) == {1: {1: "F", 2: "F", 3: "D", 4: "D"}, 2: {1: "F"}}
