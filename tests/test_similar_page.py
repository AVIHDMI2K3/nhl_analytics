"""Smoke test of the Player Similarity Score page: it asks for a player, then shows his 15 closest matches in either
mode, and offers a Compare button only once a row is clicked. Skipped when Streamlit or app_data/ is not there."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

testing = pytest.importorskip("streamlit.testing.v1")

import pandas as pd  # noqa: E402

SIMILARITY = ROOT / "app_data" / "player_similarity.parquet"


def open_similar():
    """Open the app at Home, then move to the Player Similarity Score page, the way a visitor would."""
    if not SIMILARITY.is_file():
        pytest.skip("app_data/ not exported yet")
    app = testing.AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=60).run()
    return app.switch_page("pages/5_Player_Similarity_Score.py").run()


def entries_of_2025():
    table = pd.read_parquet(SIMILARITY, partitioning=None)
    return table[(table["season"] == 2025) & (table["mode"] == "same_season")].drop_duplicates("player_id")


def test_page_asks_for_a_player_first():
    app = open_similar()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.info) == 1
    assert len(app.dataframe) == 0


def test_picker_lists_exactly_the_players_with_entries():
    entries = entries_of_2025()
    app = open_similar()
    assert len(app.selectbox(key="player").options) == len(entries)


def test_a_player_shows_fifteen_matches_in_each_mode():
    player_id = int(entries_of_2025()["player_id"].iloc[0])
    app = open_similar()
    app.selectbox(key="player").select(player_id).run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.info) == 0
    assert len(app.dataframe) == 1
    assert len(app.dataframe[0].value) == 15
    assert len(app.button) == 0
    app.radio(key="mode").set_value("all_seasons").run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.dataframe[0].value) == 15
