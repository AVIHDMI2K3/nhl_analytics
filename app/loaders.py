"""Loads the app's tables from app_data/. Each table is read once and kept in memory (cached) so a click on the
page does not read the file again. Pages call these functions and never build file paths themselves."""

import pandas as pd
import streamlit as st
from shared import settings


@st.cache_data(show_spinner=False)
def _read(table, season=None):
    folder = settings.APP_DATA_ROOT if season is None else settings.APP_DATA_ROOT / f"season={season}"
    return pd.read_parquet(folder / f"{table}.parquet")


def load_players(season):
    """Skaters of one season: basic, 5v5, power-play, penalty-kill and faceoff columns (player_season_app)."""
    return _read("player_season_app", season)


def load_goalies(season):
    """Goalies of one season: record, overall and by-situation save numbers (goalie_season_display)."""
    return _read("goalie_season_display", season)
