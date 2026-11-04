"""Tests for the Phase 4.2 stint logic. A tiny made-up game, no real data.

Teams: home = 1 (goalie 10), away = 2 (goalie 40).
"""

import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform")
)

import build_stints  # noqa: E402
import stints  # noqa: E402

GAME = {"game_id": 1, "home_team_id": 1, "away_team_id": 2}


def shift(player, team, start, end, period=1, goalie=False):
    return {
        "game_id": 1, "player_id": player, "team_id": team, "period": period,
        "start_game_seconds": start, "end_game_seconds": end, "is_goalie": goalie,
    }


def full_ice(start=0, end=60, home=range(11, 16), away=range(21, 26), period=1):
    rows = [shift(10, 1, start, end, period, True), shift(40, 2, start, end, period, True)]
    rows += [shift(p, 1, start, end, period) for p in home]
    rows += [shift(p, 2, start, end, period) for p in away]
    return rows


def test_a_line_change_starts_a_new_stint():
    rows = full_ice(0, 60) + full_ice(60, 120, home=range(16, 21), away=range(26, 31))
    result = stints.build_stints(GAME, rows)
    assert [(s["start"], s["end"]) for s in result] == [(0, 60), (60, 120)]
    assert result[0]["home_skater_ids"] == [11, 12, 13, 14, 15]
    assert result[1]["away_skater_ids"] == [26, 27, 28, 29, 30]
    assert result[1]["home_goalie_ids"] == [10]


def test_touching_shifts_of_the_same_players_do_not_split_a_stint():
    rows = full_ice(0, 30) + full_ice(30, 60)
    result = stints.build_stints(GAME, rows)
    assert [(s["start"], s["end"]) for s in result] == [(0, 60)]


def test_one_player_changing_splits_the_stint():
    rows = full_ice(0, 60)
    rows = [r for r in rows if r["player_id"] != 15]
    rows += [shift(15, 1, 0, 20), shift(16, 1, 20, 60)]
    result = stints.build_stints(GAME, rows)
    assert [(s["start"], s["end"]) for s in result] == [(0, 20), (20, 60)]
    assert result[1]["home_skater_ids"] == [11, 12, 13, 14, 16]


def test_stints_do_not_cross_periods_or_cover_gaps():
    rows = full_ice(1100, 1200, period=1) + full_ice(1200, 1300, period=2)
    result = stints.build_stints(GAME, rows)
    assert [(s["period"], s["start"], s["end"]) for s in result] == [(1, 1100, 1200), (2, 1200, 1300)]


def test_strength_from_shifts_power_play_and_goalie_adjustment():
    rows = full_ice(0, 60, home=range(11, 15))  # home 4 skaters, away 5
    stint = stints.build_stints(GAME, rows)[0]
    assert stints.strength_from_shifts(stint, "home") == "sh"
    assert stints.strength_from_shifts(stint, "away") == "pp"

    pulled = [r for r in full_ice(0, 60) if r["player_id"] != 40] + [shift(26, 2, 0, 60)]
    stint = stints.build_stints(GAME, pulled)[0]  # away: 6 skaters, no goalie
    assert stints.strength_from_shifts(stint, "away", adjust_goalie=True) == "ev"
    assert stints.strength_from_shifts(stint, "away", adjust_goalie=False) == "pp"
    assert stints.strength_from_shifts(stint, "home", adjust_goalie=False) == "sh"


def test_strength_from_code():
    assert stints.strength_from_code("1551", "home") == "ev"
    assert stints.strength_from_code("1451", "home") == "pp"  # away 4, home 5
    assert stints.strength_from_code("1451", "away") == "sh"
    assert stints.strength_from_code("0651", "away") == "ev"  # extra attacker, not a power play
    assert stints.strength_from_code("0641", "away") == "pp"
    assert stints.strength_from_code("bad", "home") is None
    assert stints.strength_from_code(None, "home") is None


def test_code_steps_previous_and_next():
    events = [
        {"game_seconds": 0, "sort_order": 1, "situation_code": "1551", "period_type": "REG"},
        {"game_seconds": 50, "sort_order": 2, "situation_code": "1451", "period_type": "REG"},
        {"game_seconds": 50, "sort_order": 3, "situation_code": "1441", "period_type": "REG"},
        {"game_seconds": 90, "sort_order": 4, "situation_code": None, "period_type": "REG"},
    ]
    steps = stints.CodeSteps(events)
    assert steps.previous(10) == "1551"
    assert steps.previous(50) == "1441"  # the last of two events at the same second
    assert steps.next(10) == "1451"
    assert steps.next(50) is None
    assert steps.previous(-1) is None


def test_seconds_by_strength_adds_up_per_player():
    rows = full_ice(0, 60) + full_ice(60, 100, home=range(16, 20))  # then home is a man down
    result = stints.build_stints(GAME, rows)
    totals = stints.seconds_by_strength(
        result, lambda stint, side: stints.strength_from_shifts(stint, side)
    )
    assert totals[(11, "ev")] == 60 and totals[(11, "sh")] == 0
    assert totals[(16, "sh")] == 40
    assert totals[(21, "ev")] == 60 and totals[(21, "pp")] == 40


def test_short_blips_in_strength_are_smoothed_away():
    # home has 5 skaters 0-60, a 2-second stretch with 6 at 60-62, then 5 again 62-120
    rows = full_ice(0, 60) + full_ice(62, 120)
    rows += full_ice(60, 62, home=range(11, 17))
    rows = [r for r in rows if not (r["player_id"] in (10, 40) and r["start_game_seconds"] != 0)]
    rows += [shift(10, 1, 60, 120, goalie=True), shift(40, 2, 60, 120, goalie=True)]
    result = stints.build_stints(GAME, rows)
    base = lambda stint, side: stints.strength_from_shifts(stint, side)  # noqa: E731
    assert [base(s, "home") for s in result] == ["ev", "pp", "ev"]
    smoothed = stints.smoothed_label_for(result, base, 2)
    assert [smoothed(s, "home") for s in result] == ["ev", "ev", "ev"]
    assert [base(s, "away") for s in result] == ["ev", "sh", "ev"]
    assert [smoothed(s, "away") for s in result] == ["ev", "ev", "ev"]
    not_smoothed = stints.smoothed_label_for(result, base, 1)
    assert [not_smoothed(s, "home") for s in result] == ["ev", "pp", "ev"]


def test_long_stretches_are_not_smoothed():
    rows = full_ice(0, 60) + full_ice(60, 100, home=range(11, 17)) + full_ice(100, 160)
    rows = [r for r in rows if not (r["player_id"] in (10, 40) and r["start_game_seconds"] != 0)]
    rows += [shift(10, 1, 60, 160, goalie=True), shift(40, 2, 60, 160, goalie=True)]
    result = stints.build_stints(GAME, rows)
    smoothed = stints.smoothed_label_for(
        result, lambda stint, side: stints.strength_from_shifts(stint, side), 5
    )
    assert [smoothed(s, "home") for s in result] == ["ev", "pp", "ev"]


def test_stint_rows_have_real_skaters_and_strength():
    pulled = [r for r in full_ice(0, 60) if r["player_id"] != 40] + [shift(26, 2, 0, 60)]
    pulled += full_ice(60, 120, home=range(11, 15))  # then home is a man down
    pulled = [r for r in pulled if not (r["player_id"] == 40 and r["start_game_seconds"] == 60)] + [
        shift(40, 2, 60, 120, goalie=True)
    ]
    rows = stints.stint_rows(GAME, stints.build_stints(GAME, pulled))
    first, second = rows
    assert (first["start_game_seconds"], first["end_game_seconds"], first["seconds"]) == (0, 60, 60)
    assert (first["away_real_skaters"], first["home_real_skaters"]) == (5, 5)  # extra attacker
    assert (first["home_strength"], first["away_strength"]) == ("ev", "ev")
    assert (second["home_real_skaters"], second["home_strength"], second["away_strength"]) == (4, "sh", "pp")
    assert second["home_goalie_ids"] == [10]


def test_stints_parquet_round_trip(tmp_path):
    rows = stints.stint_rows(GAME, stints.build_stints(GAME, full_ice(0, 60)))
    rows[0]["season"] = 2025
    path = tmp_path / "stints.parquet"
    build_stints.write_table(path, rows)
    table = pq.read_table(path)
    assert table.column_names == [name for name, _ in build_stints.SCHEMA]
    assert table.column("home_skater_ids").to_pylist()[0] == [11, 12, 13, 14, 15]
    assert table.column("home_strength").to_pylist() == ["ev"]


def test_stint_index_boundaries():
    rows = [
        {"start_game_seconds": 0, "end_game_seconds": 60, "name": "first"},
        {"start_game_seconds": 60, "end_game_seconds": 120, "name": "second"},
    ]
    index = stints.StintIndex(rows)
    assert index.at(60)["name"] == "second"
    assert index.at(60, end_inclusive=True)["name"] == "first"
    assert index.at(0)["name"] == "first" and index.at(0, end_inclusive=True) is None
    assert index.at(120) is None and index.at(120, end_inclusive=True)["name"] == "second"
    assert index.at(500) is None and index.at(500, end_inclusive=True) is None