"""Smoke test: each app page runs without an error against the exported data. Skipped when Streamlit or
app_data/ is not there."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

testing = pytest.importorskip("streamlit.testing.v1")

PAGES = ["Home.py", "pages/1_Players.py", "pages/2_Stat_Definitions.py"]


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_without_an_error(page):
    if not (ROOT / "app_data" / "season=2025" / "player_season_app.parquet").is_file():
        pytest.skip("app_data/ not exported yet")
    app = testing.AppTest.from_file(str(ROOT / "app" / page), default_timeout=60).run()
    assert not app.exception, [e.value for e in app.exception]


def test_players_page_shows_a_table_with_grouped_headers():
    if not (ROOT / "app_data" / "season=2025" / "player_season_app.parquet").is_file():
        pytest.skip("app_data/ not exported yet")
    app = testing.AppTest.from_file(str(ROOT / "app" / "pages" / "1_Players.py"), default_timeout=60).run()
    assert len(app.dataframe) == 1
    assert app.dataframe[0].value.columns.nlevels == 2


def test_players_page_shows_every_column_and_the_goalie_view():
    if not (ROOT / "app_data" / "season=2025" / "goalie_season_display.parquet").is_file():
        pytest.skip("app_data/ not exported yet")
    app = testing.AppTest.from_file(str(ROOT / "app" / "pages" / "1_Players.py"), default_timeout=60).run()
    assert len(app.dataframe[0].value.columns) == 58  # 56 stats + team and position (name is the index)
    app.radio[0].set_value("Goalies").run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.dataframe) == 1
