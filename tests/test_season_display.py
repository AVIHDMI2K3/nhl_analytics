"""Tests for the fan-facing season table. Made-up totals, no real data."""

import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform")
)

import build_season_display  # noqa: E402
import season_display  # noqa: E402
import season_totals  # noqa: E402


def total(player=7, team=1, date="2025-10-10", position="C", games=10, **numbers):
    row = {column: 0 for column in season_totals.SUM_COLUMNS}
    row.update(numbers)
    row.update(player_id=player, team_id=team, name=f"P{player}", position=position,
               games_played=games, first_game_date=date)
    return row


ABBREVS = {1: "AAA", 2: "BBB", 3: "CCC"}


def build(rows, names=None):
    return season_display.build_season_display(rows, names or {}, ABBREVS)


def test_a_player_with_one_team_has_one_team_row():
    rows = build([total(goals=5, toi_seconds=7200)])
    assert [(r["kind"], r["team"], r["teams"]) for r in rows] == [("team", "AAA", "AAA")]


def test_a_traded_player_has_a_combined_row_then_each_team_in_order_joined():
    rows = build([
        total(team=2, date="2025-12-01", games=6, goals=2, toi_seconds=3600),
        total(team=1, date="2025-10-10", games=10, goals=3, toi_seconds=7200),
    ])
    assert [(r["kind"], r["team"]) for r in rows] == [("total", "TOT"), ("team", "AAA"), ("team", "BBB")]
    combined = rows[0]
    assert combined["teams"] == "AAA, BBB" and combined["games_played"] == 16 and combined["goals"] == 5
    assert combined["toi_seconds"] == 10800 and combined["team_id"] is None


def test_three_teams_give_three_team_rows_and_one_combined_row():
    rows = build([total(team=t, date=f"2025-1{t}-01", goals=1) for t in (1, 2, 3)])
    assert [r["team"] for r in rows] == ["TOT", "AAA", "BBB", "CCC"]
    assert rows[0]["goals"] == 3


def test_rates_use_each_rows_own_totals():
    rows = build([
        total(team=1, date="2025-10-01", games=10, goals=10, sog=40, points=10, toi_seconds=7200),
        total(team=2, date="2025-12-01", games=10, goals=0, sog=10, points=0, toi_seconds=7200),
    ])
    combined, first, second = rows
    assert first["goals_per_60"] == 5.0 and second["goals_per_60"] == 0.0
    assert combined["goals_per_60"] == 10 * 3600 / 14400  # from the combined totals, not an average of rates
    assert first["shooting_pct"] == 25.0 and combined["shooting_pct"] == 20.0
    assert first["toi_per_game_seconds"] == 720


def test_rates_are_none_when_the_divisor_is_zero():
    row = build([total(games=0, toi_seconds=0, sog=0, goals=0)])[0]
    assert row["goals_per_60"] is None and row["shooting_pct"] is None and row["toi_per_game_seconds"] is None


def test_full_name_is_used_when_known_and_position_of_the_combined_row_follows_games():
    rows = build(
        [total(team=1, date="2025-10-01", games=3, position="L"), total(team=2, date="2025-11-01", games=9, position="C")],
        names={7: "Seven Player"},
    )
    assert {r["name"] for r in rows} == {"Seven Player"} and rows[0]["position"] == "C"


def test_parquet_round_trip(tmp_path):
    rows = build([total(goals=1, sog=4, toi_seconds=600)])
    for row in rows:
        row["season"] = 2025
    build_season_display.write_table(tmp_path / "t.parquet", rows)
    table = pq.read_table(tmp_path / "t.parquet")
    assert table.column_names == build_season_display.SCHEMA.names
    assert table.column("shooting_pct").to_pylist() == [25.0]

# ---- goalies ----------------------------------------------------------------


def goalie_total(player=40, team=1, date="2025-10-10", games=10, **numbers):
    row = {column: 0 for column in season_totals.GOALIE_COLUMNS}
    row.update(numbers)
    row.update(player_id=player, team_id=team, name=f"G{player}", position="G",
               games_played=games, first_game_date=date)
    return row


def build_goalies(rows, names=None):
    return season_display.build_goalie_display(rows, names or {}, ABBREVS)


def test_goalie_rates_come_from_the_rows_own_totals():
    row = build_goalies([goalie_total(
        games=2, toi_seconds=7200, shots_against=60, saves=54, goals_against=6,
        even_strength_shots_against=40, even_strength_goals_against=3,
        power_play_shots_against=20, power_play_goals_against=3,
    )])[0]
    assert row["save_pct"] == 90.0 and row["goals_against_avg"] == 3.0 and row["shots_against_per_60"] == 30.0
    assert row["even_strength_save_pct"] == 92.5 and row["power_play_save_pct"] == 85.0
    assert row["shorthanded_save_pct"] is None and row["toi_per_game_seconds"] == 3600


def test_goalie_rates_are_none_when_the_divisor_is_zero():
    row = build_goalies([goalie_total(games=0)])[0]
    assert row["save_pct"] is None and row["goals_against_avg"] is None and row["toi_per_game_seconds"] is None


def test_a_traded_goalie_has_a_combined_row_with_save_percentage_from_the_added_totals():
    rows = build_goalies([
        goalie_total(team=1, date="2025-10-01", games=10, toi_seconds=36000, shots_against=300, saves=270, goals_against=30, wins=5),
        goalie_total(team=2, date="2025-12-01", games=10, toi_seconds=36000, shots_against=100, saves=80, goals_against=20, wins=2),
    ])
    combined, first, second = rows
    assert [(r["kind"], r["team"]) for r in rows] == [("total", "TOT"), ("team", "AAA"), ("team", "BBB")]
    assert combined["wins"] == 7 and combined["games_played"] == 20 and combined["shots_against"] == 400
    assert combined["save_pct"] == 87.5 and first["save_pct"] == 90.0 and second["save_pct"] == 80.0


def test_goalie_parquet_round_trip(tmp_path):
    rows = build_goalies([goalie_total(toi_seconds=3600, shots_against=30, saves=27, goals_against=3)])
    for row in rows:
        row["season"] = 2025
    build_season_display.write_table(tmp_path / "g.parquet", rows, build_season_display.GOALIE_SCHEMA)
    table = pq.read_table(tmp_path / "g.parquet")
    assert table.column_names == build_season_display.GOALIE_SCHEMA.names
    assert table.column("save_pct").to_pylist() == [90.0]