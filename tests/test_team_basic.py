"""Tests for the team season basic stats. Made-up games and boxscore rows, no real data."""

import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform"))

import build_team_basic  # noqa: E402
import team_basic  # noqa: E402


def game(game_id, home, away, home_score, away_score, ended="REG", game_type=2, has_boxscore=True):
    return {
        "game_id": game_id,
        "game_type": game_type,
        "has_boxscore": has_boxscore,
        "home_team_id": home,
        "away_team_id": away,
        "home_score": home_score,
        "away_score": away_score,
        "last_period_type": ended,
    }


def player(game_id, team, group="forwards", **numbers):
    row = {
        "game_id": game_id,
        "team_id": team,
        "player_group": group,
        "sog": 0,
        "hits": 0,
        "blocked_shots": 0,
        "giveaways": 0,
        "takeaways": 0,
        "pim": 0,
        "power_play_goals": 0,
        "power_play_goals_against": 0,
    }
    row.update(numbers)
    return row


def by_team(rows):
    return {r["team_id"]: r for r in rows}


def test_record_points_and_overtime_rules():
    games = [
        game(1, 1, 2, 3, 1, "REG"),  # team 1 wins in regulation
        game(2, 1, 2, 2, 3, "OT"),  # team 2 wins in overtime, team 1 loses in overtime
        game(3, 2, 1, 4, 3, "SO"),  # team 2 wins in a shootout, team 1 loses in a shootout
    ]
    rows, notes = team_basic.build_team_basic(games, [])
    one, two = by_team(rows)[1], by_team(rows)[2]
    assert (one["wins"], one["losses"], one["ot_losses"], one["points"]) == (1, 0, 2, 4)
    assert (two["wins"], two["losses"], two["ot_losses"], two["points"]) == (2, 1, 0, 4)
    assert (one["regulation_wins"], one["row"]) == (1, 1)
    assert (two["regulation_wins"], two["row"]) == (0, 1)  # the overtime win counts for ROW, the shootout does not
    assert one["goals_for"] == 8 and one["goals_against"] == 8 and one["goal_diff"] == 0
    assert one["games_played"] == 3 and one["points_pct"] == 4 / 6
    assert not notes


def test_other_game_types_and_games_without_boxscore_or_score_are_left_out():
    rows, notes = team_basic.build_team_basic(
        [
            game(1, 1, 2, 1, 0),
            game(2, 1, 2, 1, 0, game_type=3),
            game(3, 1, 2, 1, 0, has_boxscore=False),
            game(4, 1, 2, None, None),
        ],
        [],
    )
    assert by_team(rows)[1]["games_played"] == 1 and notes["games_without_score"] == 1


def test_boxscore_sums_and_shots_against_are_the_opponents_shots():
    box = [
        player(1, 1, sog=3, hits=2, blocked_shots=1, giveaways=1, takeaways=2, pim=2, power_play_goals=1),
        player(1, 1, sog=2, hits=1),
        player(1, 2, sog=4, hits=5),
        player(1, 1, group="goalies", pim=2, power_play_goals_against=0),
        player(1, 2, group="goalies", power_play_goals_against=1),
        player(9, 1, sog=50),  # a game that is not in the season
    ]
    rows, _ = team_basic.build_team_basic([game(1, 1, 2, 3, 1)], box)
    one, two = by_team(rows)[1], by_team(rows)[2]
    assert (one["shots_for"], one["shots_against"]) == (5, 4) and (two["shots_for"], two["shots_against"]) == (4, 5)
    assert (one["hits"], one["blocked_shots"], one["giveaways"], one["takeaways"], one["pim"]) == (3, 1, 1, 2, 4)
    assert one["pp_goals_for"] == 1 and two["pp_goals_against"] == 1 and one["pp_goals_against"] == 0
    assert one["shots_for_per_game"] == 5.0


def test_parquet_round_trip(tmp_path):
    rows, _ = team_basic.build_team_basic([game(1, 1, 2, 3, 1)], [player(1, 1, sog=3)])
    for row in rows:
        row.update(season=2025, team="AAA")
    build_team_basic.write_table(tmp_path / "t.parquet", rows)
    table = pq.read_table(tmp_path / "t.parquet")
    assert table.column_names == build_team_basic.SCHEMA.names and table.num_rows == 2
