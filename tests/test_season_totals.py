"""Tests for the season totals from the boxscore (skaters and goalies). Made-up rows, no real data."""

import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform")
)

import build_season_totals  # noqa: E402
import season_totals  # noqa: E402

REGULAR = {1, 2, 3, 4}
DATES = {1: "2025-10-01", 2: "2025-10-05", 3: "2025-12-01", 4: "2025-12-05"}


def skater(game=1, player=7, team=1, toi=1000, position="C", **numbers):
    row = {column: 0 for column in season_totals.SUM_COLUMNS}
    row.update(numbers)
    row.update(game_id=game, player_id=player, team_id=team, player_group="forwards", name=f"S{player}",
               position=position, toi_seconds=toi)
    return row


def goalie(game=1, player=40, team=1, toi=3600, starter=True, decision=None, against=0,
           ev=(0, 0), pp=(0, 0), sh=(0, 0), shots=0, **extra):
    """A goalie row. `ev`, `pp` and `sh` are (saves, shots) for each strength."""
    row = {column: 0 for column in season_totals.GOALIE_SUM_COLUMNS}
    row.update(
        game_id=game, player_id=player, team_id=team, player_group="goalies", name=f"G{player}", position="G",
        toi_seconds=toi, starter=starter, decision=decision, goals_against=against, shots_against=shots,
        saves=shots - against,
        even_strength_shots_against=f"{ev[0]}/{ev[1]}", power_play_shots_against=f"{pp[0]}/{pp[1]}",
        shorthanded_shots_against=f"{sh[0]}/{sh[1]}",
    )
    row.update(extra)
    return row


# ---- skaters ----------------------------------------------------------------


def test_skaters_are_summed_and_goalies_and_other_game_types_are_left_out():
    rows = [
        skater(game=1, goals=1, assists=2, toi=1000),
        skater(game=2, goals=2, toi=1100),
        skater(game=9, goals=5),  # not a regular-season game with a boxscore
        goalie(game=1),
    ]
    out = season_totals.build_player_season_totals(rows, REGULAR, DATES)
    assert len(out) == 1
    assert out[0]["goals"] == 3 and out[0]["assists"] == 2 and out[0]["toi_seconds"] == 2100
    assert out[0]["games_played"] == 2 and out[0]["first_game_date"] == "2025-10-01"


def test_games_played_counts_only_games_with_time_on_ice_and_none_counts_as_zero():
    rows = [skater(game=1, toi=900), skater(game=2, toi=0), skater(game=3, toi=None, goals=None)]
    out = season_totals.build_player_season_totals(rows, REGULAR, DATES)[0]
    assert out["games_played"] == 1 and out["goals"] == 0 and out["toi_seconds"] == 900


def test_a_traded_skater_has_one_row_per_team():
    rows = [skater(game=1, team=1, goals=1), skater(game=3, team=2, goals=4)]
    out = season_totals.build_player_season_totals(rows, REGULAR, DATES)
    assert [(r["team_id"], r["goals"], r["first_game_date"]) for r in out] == [(1, 1, "2025-10-01"), (2, 4, "2025-12-01")]


def test_the_position_is_the_one_most_often_listed():
    rows = [skater(game=1, position="L"), skater(game=2, position="C"), skater(game=3, position="C")]
    assert season_totals.build_player_season_totals(rows, REGULAR, DATES)[0]["position"] == "C"


# ---- goalies ----------------------------------------------------------------


def test_shots_in_reads_the_saves_over_shots_text():
    assert season_totals.shots_in("15/17") == 17
    assert season_totals.shots_in("0/0") == 0
    for bad in (None, "", "15", "a/b", 17):
        assert season_totals.shots_in(bad) == 0


def test_goalie_totals_sum_games_starts_decisions_and_shots():
    rows = [
        goalie(game=1, decision="W", against=2, shots=19, ev=(15, 17), pp=(2, 2)),
        goalie(game=2, decision="L", against=3, shots=30, ev=(22, 25), pp=(3, 4), sh=(2, 1 + 0)),
        goalie(game=3, decision="O", against=1, shots=10, ev=(9, 10)),
        goalie(game=4, starter=False, toi=0),  # dressed, did not play
        skater(game=1),
    ]
    out = season_totals.build_goalie_season_totals(rows, REGULAR, DATES)
    assert len(out) == 1
    row = out[0]
    assert row["games_played"] == 3 and row["games_started"] == 3 and row["position"] == "G"
    assert (row["wins"], row["losses"], row["ot_losses"]) == (1, 1, 1)
    assert row["shots_against"] == 59 and row["goals_against"] == 6 and row["saves"] == 53
    assert row["even_strength_shots_against"] == 52 and row["power_play_shots_against"] == 6
    assert row["shorthanded_shots_against"] == 1
    assert row["toi_seconds"] == 3 * 3600 and row["first_game_date"] == "2025-10-01"


def test_a_goalie_who_did_not_play_has_zero_games_played_but_still_a_row():
    out = season_totals.build_goalie_season_totals([goalie(game=1, starter=False, toi=0)], REGULAR, DATES)
    assert out[0]["games_played"] == 0 and out[0]["games_started"] == 0 and out[0]["first_game_date"] is None


def test_a_shutout_needs_all_of_the_teams_goalie_time_and_no_goals_against():
    rows = [
        goalie(game=1, against=0, shots=20, decision="W"),  # won, played everything, nothing allowed: a shutout
        goalie(game=2, against=1, shots=20),  # allowed one
        goalie(game=3, player=40, toi=2400, against=0, shots=10, decision="W"),  # relieved, nothing allowed: not a shutout
        goalie(game=3, player=41, toi=1200, starter=False, against=0, shots=8, decision="W"),
        goalie(game=4, player=42, against=0, shots=20, decision="L"),  # lost in regulation: not a shutout
        goalie(game=4, player=43, team=2, toi=3900, against=0, shots=20, decision="O"),  # lost the shootout of a 0-0 game: a shutout
    ]
    out = {r["player_id"]: r for r in season_totals.build_goalie_season_totals(rows, REGULAR, DATES)}
    assert out[40]["shutouts"] == 1 and out[41]["shutouts"] == 0
    assert out[42]["shutouts"] == 0 and out[43]["shutouts"] == 1


def test_a_shutout_in_overtime_counts_when_he_played_all_of_the_teams_time():
    rows = [goalie(game=1, toi=3900, against=0, shots=25, decision="W")]
    assert season_totals.build_goalie_season_totals(rows, REGULAR, DATES)[0]["shutouts"] == 1


def test_a_traded_goalie_has_one_row_per_team_and_the_other_team_is_not_mixed_in():
    rows = [
        goalie(game=1, team=1, decision="W", shots=20),
        goalie(game=1, player=50, team=2, decision="L", shots=30),  # the opponent's goalie
        goalie(game=3, team=2, decision="L", shots=25),
    ]
    out = season_totals.build_goalie_season_totals(rows, REGULAR, DATES)
    mine = [(r["team_id"], r["wins"], r["losses"], r["shots_against"]) for r in out if r["player_id"] == 40]
    assert mine == [(1, 1, 0, 20), (2, 0, 1, 25)]


def test_goalie_games_outside_the_regular_season_are_left_out():
    out = season_totals.build_goalie_season_totals([goalie(game=9, decision="W", shots=30)], REGULAR, DATES)
    assert out == []


# ---- the tables on disk -----------------------------------------------------


def test_parquet_round_trip_of_both_tables(tmp_path):
    skater_rows = season_totals.build_player_season_totals([skater(goals=2)], REGULAR, DATES)
    goalie_rows = season_totals.build_goalie_season_totals([goalie(decision="W", against=1, shots=11)], REGULAR, DATES)
    for rows in (skater_rows, goalie_rows):
        for row in rows:
            row["season"] = 2025
    build_season_totals.write_table(tmp_path / "s.parquet", skater_rows)
    build_season_totals.write_table(tmp_path / "g.parquet", goalie_rows, build_season_totals.GOALIE_SCHEMA)
    assert pq.read_table(tmp_path / "s.parquet").column_names == build_season_totals.SCHEMA.names
    table = pq.read_table(tmp_path / "g.parquet")
    assert table.column_names == build_season_totals.GOALIE_SCHEMA.names
    assert table.column("wins").to_pylist() == [1] and table.column("shots_against").to_pylist() == [11]


def test_the_boxscore_columns_read_have_no_duplicates():
    columns = build_season_totals.BOX_COLUMNS
    assert len(columns) == len(set(columns))
    assert {"starter", "decision", "even_strength_shots_against", "goals_against"} <= set(columns)
    # worked-out columns are not in the boxscore and must not be asked for
    assert not set(season_totals.GOALIE_COUNT_COLUMNS) & set(columns)