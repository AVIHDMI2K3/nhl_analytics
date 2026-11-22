"""Tests for app/table_view.py and config/settings.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
import table_view as tv  # noqa: E402
from shared import labels, settings  # noqa: E402

PLAYER_IDS = {"Auston Matthews": 1, "Quinn Hughes": 2, "Fringe Winger": 3}


def player(name, team="TOR", teams=None, kind="team", position="C", minutes=900.0, **extra):
    return {
        "name": name,
        "player_id": PLAYER_IDS[name],
        "team": team,
        "teams": teams or team,
        "kind": kind,
        "position": position,
        "minutes_5v5": minutes,
        **extra,
    }


@pytest.fixture
def df():
    return pd.DataFrame(
        [
            player("Auston Matthews", "TOR", games_played=60, cf_pct_5v5=46.24, toi_per_game_seconds=1260.0),
            player(
                "Quinn Hughes",
                "VAN",
                teams="VAN, MIN",
                position="D",
                minutes=525.6,
                games_played=26,
                cf_pct_5v5=53.7,
                toi_per_game_seconds=1500.0,
            ),
            player(
                "Quinn Hughes",
                "MIN",
                teams="VAN, MIN",
                position="D",
                minutes=1080.2,
                games_played=48,
                cf_pct_5v5=52.6,
                toi_per_game_seconds=1500.0,
            ),
            player(
                "Quinn Hughes",
                "TOT",
                teams="VAN, MIN",
                kind="total",
                position="D",
                minutes=1605.8,
                games_played=74,
                cf_pct_5v5=53.0,
                toi_per_game_seconds=1500.0,
            ),
            player(
                "Fringe Winger",
                "TOR",
                position="L",
                minutes=None,
                games_played=3,
                cf_pct_5v5=None,
                toi_per_game_seconds=300.0,
            ),
        ]
    )


def test_shown_rows_keeps_the_combined_row_and_single_team_players(df):
    rows = tv.shown_rows(df)
    assert list(rows["name"]) == ["Auston Matthews", "Quinn Hughes", "Fringe Winger"]
    assert list(rows["team"]) == ["TOR", "TOT", "TOR"]


def test_team_options_are_the_individual_teams(df):
    assert tv.team_options(df) == ["MIN", "TOR", "VAN"]


def test_team_filter_finds_a_traded_player_under_each_team(df):
    for team in ("VAN", "MIN"):
        assert list(tv.filter_players(df, team=team, min_minutes=0)["team"]) == ["TOT"]
    assert list(tv.filter_players(df, team="TOR", min_minutes=0)["name"]) == ["Auston Matthews", "Fringe Winger"]


def test_position_filter(df):
    assert list(tv.filter_players(df, position="Defensemen", min_minutes=0)["name"]) == ["Quinn Hughes"]
    assert set(tv.filter_players(df, position="Forwards", min_minutes=0)["position"]) == {"C", "L"}


def test_name_search_ignores_case(df):
    assert list(tv.filter_players(df, name="  matth ", min_minutes=0)["name"]) == ["Auston Matthews"]


def test_minimum_minutes_drops_players_with_none(df):
    assert list(tv.filter_players(df, min_minutes=600)["name"]) == ["Auston Matthews", "Quinn Hughes"]
    assert "Fringe Winger" in set(tv.filter_players(df, min_minutes=0)["name"])


def test_all_columns_cover_every_group_in_order():
    assert tv.all_columns("players") == [c for _, cols in labels.GROUPS["players"] for c in cols]
    assert len(tv.all_columns("goalies")) == 24


def test_name_as_index_keeps_the_name_out_of_the_columns(df):
    rows = tv.filter_players(df, min_minutes=0)
    frame = tv.grouped_frame(rows, df, "players", ["games_played"], name_as_index=True)
    assert list(frame.index) == ["Auston Matthews", "Quinn Hughes", "Fringe Winger"]
    assert frame.columns[0] == ("", labels.label("team"))


def test_goalie_save_percentages_show_as_fractions():
    goalies = pd.DataFrame({"name": ["A", "B"], "team": ["TOR", "VAN"], "save_pct": [91.54, 90.12]})
    frame = tv.grouped_frame(goalies, goalies, "goalies", ["save_pct"])
    assert list(frame[("Overall", labels.label("save_pct"))]) == [0.915, 0.901]


def test_definitions_cover_every_shown_column():
    for table in ("players", "teams", "goalies", "lines"):
        groups = tv.definitions(table)
        stats = sum(len(frame) for _, frame in groups)
        assert stats == len(labels.FIXED[table]) + len(tv.all_columns(table))
        assert all(frame["Meaning"].str.len().gt(0).all() for _, frame in groups)
    assert tv.definitions("players")[0][0] == "Row"
    assert list(tv.definitions("goalies")[1][1].columns) == ["Stat", "Meaning"]


def test_filter_goalies_by_games_and_team():
    goalies = pd.DataFrame(
        {
            "name": ["A", "B"],
            "player_id": [1, 2],
            "team": ["TOR", "VAN"],
            "teams": ["TOR", "VAN"],
            "kind": ["team", "team"],
            "games_played": [50, 5],
        }
    )
    assert list(tv.filter_goalies(goalies, min_games=10)["name"]) == ["A"]
    assert list(tv.filter_goalies(goalies, team="VAN")["name"]) == ["B"]
    assert list(tv.filter_goalies(goalies, name="a")["name"]) == ["A"]


def test_grouped_frame_headers_and_values(df):
    rows = tv.filter_players(df, min_minutes=0)
    frame = tv.grouped_frame(rows, df, "players", ["games_played", "cf_pct_5v5", "toi_per_game_seconds"])
    assert list(frame.columns) == [
        ("", "Player"),
        ("", "Team"),
        ("", labels.label("position")),
        ("Basic", "GP"),
        ("On-ice play, 5v5", "CF%"),
        ("Basic", "TOI/GP (min)"),
    ]
    assert list(frame[("Basic", "GP")]) == [60, 74, 3]
    assert str(frame[("Basic", "GP")].dtype) == "Int64"
    assert frame[("On-ice play, 5v5", "CF%")].iloc[0] == pytest.approx(46.2)
    assert pd.isna(frame[("On-ice play, 5v5", "CF%")].iloc[2])
    assert list(frame[("Basic", "TOI/GP (min)")]) == [21.0, 25.0, 5.0]


def test_whole_number_columns_stay_whole_when_the_rows_are_filtered(df):
    rows = tv.filter_players(df, name="Matthews", min_minutes=0)
    frame = tv.grouped_frame(rows, df, "players", ["games_played"])
    assert str(frame[("Basic", "GP")].dtype) == "Int64"


def test_every_column_can_be_laid_out():
    row = {c: 1.5 for _, cols in labels.GROUPS["players"] for c in cols}
    row.update({"name": "A", "team": "TOR", "position": "C"})
    full = pd.DataFrame([row])
    frame = tv.grouped_frame(full, full, "players")
    assert len(frame.columns) == len(labels.FIXED["players"]) + len(tv.all_columns("players"))


def test_season_labels_and_order():
    assert settings.season_label(2025) == "2025-26"
    assert settings.season_label(2099) == "2099-00"
    assert list(settings.SEASONS) == sorted(settings.SEASONS, reverse=True)
    assert settings.DEFAULT_MIN_MINUTES_5V5 <= settings.MAX_MIN_MINUTES_5V5


def test_traded_players_lists_only_players_with_a_total_row(df):
    rows = tv.filter_players(df, min_minutes=0)
    assert tv.traded_players(rows) == {2: "Quinn Hughes (VAN, MIN)"}


def test_team_breakdown_is_the_total_then_each_team_by_games(df):
    rows = tv.team_breakdown(df, 2)
    assert list(rows["team"]) == ["TOT", "MIN", "VAN"]
    assert list(rows["games_played"]) == [74, 48, 26]


def test_team_breakdown_of_a_one_team_player_is_that_team(df):
    assert list(tv.team_breakdown(df, 1)["team"]) == ["TOR"]
