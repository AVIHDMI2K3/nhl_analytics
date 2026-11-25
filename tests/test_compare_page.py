"""Smoke test of the Player Comparison page: it asks for two players, then shows the chart and the table. Skipped when
Streamlit or app_data/ is not there."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

testing = pytest.importorskip("streamlit.testing.v1")

import pandas as pd  # noqa: E402

PERCENTILES = ROOT / "app_data" / "season=2025" / "player_season_percentiles.parquet"


def open_compare():
    """Open the app at Home, then move to the Player Comparison page, the way a visitor would."""
    if not PERCENTILES.is_file():
        pytest.skip("app_data/ not exported yet")
    app = testing.AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=60).run()
    return app.switch_page("pages/4_Player_Comparison.py").run()


def two_forwards():
    table = pd.read_parquet(PERCENTILES, partitioning=None).drop_duplicates("player_id")
    forwards = table[table["position_group"] == "F"]
    return int(forwards["player_id"].iloc[0]), int(forwards["player_id"].iloc[1])


def test_page_asks_for_two_players_first():
    app = open_compare()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.info) == 1
    assert len(app.dataframe) == 0


def test_two_forwards_show_the_chart_and_a_table_with_every_stat():
    first, second = two_forwards()
    app = open_compare()
    app.selectbox(key="player_a").select(first).run()
    app.selectbox(key="player_b").select(second).run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.info) == 0
    assert len(app.dataframe) == 1
    assert len(app.dataframe[0].value) == 29  # one row per stat


def test_second_picker_lists_only_the_first_players_position_group():
    first, _ = two_forwards()
    app = open_compare()
    app.selectbox(key="player_a").select(first).run()
    options = app.selectbox(key="player_b").options
    assert len(options) > 100
    assert not any(option.endswith(", D)") for option in options)


def test_the_same_player_twice_in_one_season_is_not_compared():
    first, _ = two_forwards()
    app = open_compare()
    app.selectbox(key="player_a").select(first).run()
    app.selectbox(key="player_b").select(first).run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.warning) == 1
    assert len(app.dataframe) == 0
