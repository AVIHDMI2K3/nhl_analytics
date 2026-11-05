"""Tests for the goalie totals check: the shutout definitions and the per-goalie combining."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_goalie_totals  # noqa: E402

GAMES = {1, 2, 3, 4}


def goalie(game, player, team=1, toi=3600, against=0, decision="W"):
    return {
        "game_id": game, "player_id": player, "team_id": team, "player_group": "goalies",
        "toi_seconds": toi, "goals_against": against, "decision": decision,
    }


def test_shutout_definitions_get_stricter():
    box = [
        goalie(1, 30),  # clean: whole game, win, no shootout
        goalie(2, 30, toi=1800),  # won with no goals against, but another goalie played too
        goalie(2, 31, toi=1800),
        goalie(3, 30, decision="O"),  # no goals against, but no win
        goalie(4, 30, toi=3900),  # a shootout win with no goals against in 65 minutes
    ]
    variants = check_goalie_totals.shutout_variants(box, GAMES, shootout_games={4})
    assert variants[1][30] == 4 and variants[1][31] == 1
    assert variants[2][30] == 3 and variants[2][31] == 1
    assert variants[3][30] == 2 and variants[3][31] == 0
    assert variants[4][30] == 1
    assert variants[5][30] == 3 and variants[5][31] == 0  # the win, the shootout win and the shootout loss


def test_a_goal_against_or_no_time_on_ice_is_never_a_shutout():
    box = [goalie(1, 30, against=1), goalie(2, 30, toi=0)]
    variants = check_goalie_totals.shutout_variants(box, GAMES, shootout_games=set())
    assert all(sum(counts.values()) == 0 for counts in variants.values())


def test_combine_by_player_adds_the_teams_of_a_traded_goalie():
    rows = [
        {"player_id": 30, "team_id": 1, "name": "G", "games_played": 10, "saves": 200},
        {"player_id": 30, "team_id": 2, "name": "G", "games_played": 5, "saves": 100},
        {"player_id": 31, "team_id": 1, "name": "H", "games_played": 1, "saves": 20},
    ]
    combined = check_goalie_totals.combine_by_player(rows)
    assert combined[30]["games_played"] == 15 and combined[30]["saves"] == 300 and combined[31]["saves"] == 20
    assert "team_id" in combined[30] and combined[30]["team_id"] == 3  # numbers are added; the id is not used