"""Teams page: every team of the chosen season in one table, with stat groups labeled across the top."""

import loaders
import streamlit as st
import table_view
from shared import settings

TABLE = "teams"

st.set_page_config(page_title="Teams - NHL Analytics", layout="wide")
st.title("Teams")
st.caption(
    "Every team for the selected season in one table, ordered by points and then goal difference, with the stat "
    "groups labeled across the top. Click a column to sort and scroll sideways for more. What each stat means is "
    "on the Stat definitions page in the sidebar."
)

season_col, name_col, _ = st.columns([1, 2, 5])
season = season_col.selectbox("Season", settings.SEASONS, format_func=settings.season_label)
teams = loaders.load_teams(season)
name = name_col.text_input("Search team", placeholder="Name or abbreviation")

rows = table_view.filter_teams(teams, name)
st.caption(f"{len(rows)} teams. Shots and shots against are per game; the 5v5 columns are at five on five.")
frame = table_view.grouped_frame(rows, teams, TABLE, name_as_index=True)
st.dataframe(frame, height=min(1200, 36 * (len(frame) + 2)))
