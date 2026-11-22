"""Tests for the special-teams goal comparison. A tiny made-up game, no real data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import diagnose_special_teams_goals as diagnose  # noqa: E402


def trow(team, strength, goals, game=1, goalies_against=1):
    return {
        "game_id": game,
        "team_id": team,
        "strength": strength,
        "for_goal": goals,
        "goalies_against": goalies_against,
    }


def goalie(team, pp_against=0, sh_against=0, game=1, group="goalies"):
    return {
        "game_id": game,
        "team_id": team,
        "player_group": group,
        "power_play_goals_against": pp_against,
        "shorthanded_goals_against": sh_against,
    }


def test_each_teams_goals_are_compared_with_the_opponents_goalies():
    team_rows = [trow(1, "pp", 2), trow(1, "sh", 1), trow(2, "pp", 0), trow(2, "sh", 0), trow(1, "ev", 5)]
    box = [
        goalie(2, pp_against=2),  # team 2's goalie conceded 2 power-play goals: team 1's pp goals
        goalie(2, sh_against=0),
        goalie(1, sh_against=1),  # team 1's goalie conceded 1 shorthanded goal: team 2's sh goals
        goalie(1, group="forwards", pp_against=9),  # skaters are ignored
    ]
    got = {(s, t): (mine, theirs) for s, _, t, mine, theirs, *_ in diagnose.compare_by_game(team_rows, box)}
    assert got[("pp", 1)] == (2, 2) and got[("sh", 1)] == (1, 0)
    assert got[("pp", 2)] == (0, 0) and got[("sh", 2)] == (0, 1)


def test_two_goalies_of_one_team_are_added_and_missing_rows_count_as_zero():
    team_rows = [trow(1, "pp", 1), trow(2, "pp", 0)]
    box = [goalie(2, pp_against=1), goalie(2, pp_against=None)]
    got = {(s, t): (mine, theirs) for s, _, t, mine, theirs, *_ in diagnose.compare_by_game(team_rows, box)}
    assert got[("pp", 1)] == (1, 1) and got[("sh", 1)] == (0, 0)


def test_goals_into_an_empty_net_are_counted_apart():
    team_rows = [trow(1, "sh", 1), trow(1, "sh", 1, goalies_against=0), trow(2, "sh", 0)]
    box = [goalie(2, sh_against=1)]
    got = {(s, t): (mine, theirs, net) for s, _, t, mine, theirs, net, *_ in diagnose.compare_by_game(team_rows, box)}
    assert got[("sh", 1)] == (2, 1, 1)


def goal(strength_skaters, game=1, team=1, goalie_for=1, goalie_against=1):
    mine, theirs = strength_skaters
    return {
        "game_id": game,
        "team_id": team,
        "skaters_for": mine,
        "skaters_against": theirs,
        "goalie_for": goalie_for,
        "goalie_against": goalie_against,
    }


def test_code_strength_counts_a_pulled_goalie_as_no_skater():
    assert diagnose.code_strength(goal((5, 4))) == "pp"
    assert diagnose.code_strength(goal((4, 5))) == "sh"
    assert diagnose.code_strength(goal((3, 3))) == "ev"
    assert diagnose.code_strength(goal((5, 6), goalie_against=0)) == "ev"  # the other team pulled its goalie
    assert diagnose.code_strength(goal((4, 6), goalie_against=0)) == "sh"


def test_code_goals_are_counted_by_strength_and_apart_when_the_net_is_empty():
    everything, in_net = diagnose.code_goal_counts([goal((5, 4)), goal((4, 6), goalie_against=0), goal((3, 3))])
    assert everything[("pp", 1, 1)] == 1 and everything[("sh", 1, 1)] == 1 and everything[("ev", 1, 1)] == 1
    assert in_net[("sh", 1, 1)] == 0 and in_net[("pp", 1, 1)] == 1


def test_the_code_counts_are_added_to_the_comparison():
    team_rows = [trow(1, "pp", 1), trow(2, "pp", 0)]
    box = [goalie(2, pp_against=1)]
    code = diagnose.code_goal_counts([goal((5, 4))])
    row = next(r for r in diagnose.compare_by_game(team_rows, box, code) if r[0] == "pp" and r[2] == 1)
    assert row[6] == 1 and row[7] == 1
