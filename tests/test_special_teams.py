"""Tests for the power-play and penalty-kill skater stats. Made-up rows, no real data."""

import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform")
)

import build_player_special_teams  # noqa: E402
import special_teams  # noqa: E402

ABBREVS = {1: "AAA", 2: "BBB"}
PLAYER_NUMBERS = ("seconds", "for_goal", "against_goal")


def prow(game=1, player=11, team=1, strength="pp", **numbers):
    row = dict.fromkeys(PLAYER_NUMBERS, 0)
    row.update(numbers)
    row.update(game_id=game, player_id=player, team_id=team, strength=strength)
    return row


def trow(game=1, team=1, strength="pp", seconds=0):
    return {"game_id": game, "team_id": team, "strength": strength, "seconds": seconds}


def attempt(kind="goal", player=11, team=1, event=1, game=1, skaters=(5, 4), goalies=(1, 1)):
    return {"game_id": game, "event_id": event, "attempt_type": kind, "shooter_id": player, "team_id": team,
            "skaters_for": skaters[0], "skaters_against": skaters[1], "goalie_for": goalies[0], "goalie_against": goalies[1]}


def season_row(player=11, team=1, date="2025-10-01", games=10):
    return {"player_id": player, "team_id": team, "name": f"P{player}", "position": "C",
            "games_played": games, "first_game_date": date}


# ---- strength from the situation code -----------------------------------------


def test_code_strength_counts_a_pulled_goalie_as_no_skater():
    assert special_teams.code_strength(attempt(skaters=(5, 4))) == "pp"
    assert special_teams.code_strength(attempt(skaters=(4, 5))) == "sh"
    assert special_teams.code_strength(attempt(skaters=(3, 3))) == "ev"
    assert special_teams.code_strength(attempt(skaters=(5, 6), goalies=(1, 0))) == "ev"
    assert special_teams.code_strength(attempt(skaters=(4, 6), goalies=(1, 0))) == "sh"


def test_goal_assists_are_read_from_the_goal_events_only():
    events = [
        {"game_id": 1, "event_id": 5, "event_type": "goal", "assist1_player_id": 12, "assist2_player_id": None},
        {"game_id": 1, "event_id": 6, "event_type": "shot-on-goal", "assist1_player_id": 99, "assist2_player_id": 98},
    ]
    assert special_teams.goal_assists(events) == {(1, 5): (12, None)}


def test_individual_counts_give_goals_assists_points_and_shots_by_strength():
    attempts = [
        attempt("goal", player=11, event=1, skaters=(5, 4)),  # pp goal, assisted by 12 and 13
        attempt("shot-on-goal", player=11, event=2, skaters=(5, 4)),
        attempt("shot-on-goal", player=11, event=3, skaters=(5, 5)),  # even strength: not counted
        attempt("goal", player=14, event=4, skaters=(4, 5)),  # sh goal, unassisted
        attempt("missed-shot", player=11, event=5, skaters=(5, 4)),  # not a shot on goal
    ]
    counts = special_teams.individual_counts_from_code(attempts, {(1, 1): (12, 13)})
    scorer = counts[(11, 1, "pp")]
    assert (scorer["goals"], scorer["shots"], scorer["points"], scorer["assists"]) == (1, 2, 1, 0)
    assert counts[(12, 1, "pp")]["assists_primary"] == 1 and counts[(12, 1, "pp")]["points"] == 1
    assert counts[(13, 1, "pp")]["assists_secondary"] == 1 and counts[(13, 1, "pp")]["assists"] == 1
    assert counts[(14, 1, "sh")]["goals"] == 1 and counts[(14, 1, "sh")]["shots"] == 1
    assert (11, 1, "ev") not in counts and (11, 1, "sh") not in counts


def test_a_goal_into_an_empty_net_counts_for_the_scorer_and_a_missing_assist_is_skipped():
    attempts = [attempt("goal", player=11, event=7, skaters=(4, 6), goalies=(1, 0))]
    counts = special_teams.individual_counts_from_code(attempts, {(1, 7): (None, 12)})
    assert counts[(11, 1, "sh")]["goals"] == 1 and counts[(12, 1, "sh")]["assists_secondary"] == 1
    assert (None, 1, "sh") not in counts


def test_included_counts_cover_only_games_with_shift_data():
    attempts = [attempt("goal", player=11, event=1, game=1), attempt("goal", player=11, event=2, game=2)]
    counts = special_teams.individual_counts_from_code(attempts, {(1, 1): (12, None), (2, 2): (12, None)},
                                                      games={(11, 1): {1}, (12, 1): {1}})
    assert counts[(11, 1, "pp")]["goals"] == 2 and counts[(11, 1, "pp")]["included_goals"] == 1
    assert counts[(12, 1, "pp")]["assists"] == 2 and counts[(12, 1, "pp")]["included_assists"] == 1


# ---- the two sources together ---------------------------------------------------


def test_time_comes_from_the_shifts_and_counts_from_the_code_and_even_strength_only_counts_the_game():
    player_rows = [
        prow(strength="pp", seconds=100, for_goal=1),
        prow(strength="pp", seconds=20),  # a second pp state (for example 5v3) of the same game
        prow(strength="sh", seconds=50, against_goal=2),
        prow(game=2, strength="ev", seconds=999),  # a game with no special teams time
    ]
    team_rows = [trow(strength="pp", seconds=300), trow(strength="sh", seconds=200), trow(strength="ev", seconds=3000)]
    attempts = [attempt("goal", player=11, event=1), attempt("goal", player=11, event=2, game=3, skaters=(4, 5))]
    totals, games = special_teams.build_special_teams_counts(player_rows, team_rows, attempts, {(1, 1): (12, 13)})
    pp, sh = totals[(11, 1, "pp")], totals[(11, 1, "sh")]
    assert (pp["seconds"], pp["gf"], pp["team_seconds"]) == (120, 1, 300)
    assert (pp["goals"], pp["included_goals"]) == (1, 1)  # game 1 has shift data
    assert (sh["seconds"], sh["ga"], sh["team_seconds"]) == (50, 2, 200)
    assert (sh["goals"], sh["included_goals"]) == (1, 0)  # game 3 has none: counted, but not in the rates
    assert games[(11, 1)] == 2 and (11, 1, "ev") not in totals


def test_team_time_counts_only_games_the_player_played_and_players_are_kept_apart():
    player_rows = [prow(game=1, player=11, seconds=60), prow(game=1, player=12, seconds=30)]
    team_rows = [trow(game=1, seconds=300), trow(game=2, seconds=500)]  # game 2: neither played
    totals, _ = special_teams.build_special_teams_counts(player_rows, team_rows)
    assert totals[(11, 1, "pp")]["team_seconds"] == 300 and totals[(12, 1, "pp")]["seconds"] == 30


def test_a_player_with_goals_only_in_games_without_shift_data_does_not_break_the_display():
    attempts = [attempt("goal", player=11, event=1, game=9)]
    rows = build([prow(player=12, seconds=60)], [trow(seconds=300)], [season_row(player=11), season_row(player=12)], attempts)
    mine = next(r for r in rows if r["player_id"] == 11 and r["situation"] == "pp")
    assert mine["goals"] == 1 and mine["games_included"] == 0 and mine["goals_per_60"] is None


def build(player_rows, team_rows, season_rows, attempts=(), assists=None):
    totals, games = special_teams.build_special_teams_counts(player_rows, team_rows, attempts, assists)
    return special_teams.build_special_teams_display(totals, games, season_rows, {}, ABBREVS)


def test_rates_use_the_included_games_for_the_individual_counts():
    # 1800 s of power play in game 1 (shift data); a second goal in game 2 (no shift data)
    attempts = [
        attempt("goal", player=11, event=1, game=1), attempt("shot-on-goal", player=11, event=2, game=1),
        attempt("shot-on-goal", player=11, event=3, game=1), attempt("shot-on-goal", player=11, event=4, game=1),
        attempt("goal", player=11, event=5, game=2),
    ]
    rows = build([prow(game=1, seconds=1800, for_goal=4)], [trow(game=1, seconds=7200)], [season_row()], attempts,
                 {(1, 1): (None, None), (2, 5): (None, None)})
    row = next(r for r in rows if r["situation"] == "pp")
    assert (row["goals"], row["shots"], row["included_goals"], row["included_shots"]) == (2, 5, 1, 4)
    assert row["goals_per_60"] == 2.0 and row["gf_per_60"] == 8.0  # 1 goal in 1800 s; on-ice goals as they are
    assert row["shooting_pct"] == 40.0  # all games: 2 goals on 5 shots
    assert row["team_share_pct"] == 25.0 and row["toi_per_game_seconds"] == 1800
    assert (row["games_played"], row["games_included"]) == (10, 1)


def test_rates_are_none_when_the_divisor_is_zero():
    row = build([prow(seconds=0)], [trow(seconds=0)], [season_row()])[0]
    assert row["team_share_pct"] is None and row["shooting_pct"] is None and row["goals_per_60"] is None


def test_a_traded_player_has_a_combined_row_from_the_added_totals_and_one_row_per_team():
    player_rows = [prow(game=1, team=1, seconds=600), prow(game=3, team=2, seconds=1200)]
    team_rows = [trow(game=1, team=1, seconds=1200), trow(game=3, team=2, seconds=1200)]
    attempts = [attempt("goal", player=11, team=1, game=1, event=1),
                attempt("shot-on-goal", player=11, team=2, game=3, event=2),
                attempt("shot-on-goal", player=11, team=2, game=3, event=3)]
    rows = build(player_rows, team_rows, [season_row(team=1, date="2025-10-01"), season_row(team=2, date="2025-12-01")], attempts)
    pp = [r for r in rows if r["situation"] == "pp"]
    assert [(r["kind"], r["team"]) for r in pp] == [("total", "TOT"), ("team", "AAA"), ("team", "BBB")]
    total = pp[0]
    assert total["seconds"] == 1800 and total["team_seconds"] == 2400 and total["goals"] == 1 and total["shots"] == 3
    assert total["team_share_pct"] == 75.0 and total["games_included"] == 2 and total["games_played"] == 20


def test_parquet_round_trip(tmp_path):
    rows = build([prow(seconds=600, for_goal=1)], [trow(seconds=1200)], [season_row()],
                 [attempt("goal", event=1), attempt("shot-on-goal", event=2)])
    for row in rows:
        row["season"] = 2025
    build_player_special_teams.write_table(tmp_path / "t.parquet", rows)
    table = pq.read_table(tmp_path / "t.parquet")
    assert table.column_names == build_player_special_teams.SCHEMA.names
    assert table.column("shooting_pct").to_pylist()[0] == 50.0