"""Players page: one table of skaters or goalies for the chosen season, every stat shown, groups labeled on top."""

import loaders
import streamlit as st
import table_view
from shared import settings

st.set_page_config(page_title="Players - NHL Analytics", layout="wide")
st.title("Players")
st.caption(
    "One table for the selected season with every stat, grouped under labels across the top. Click a column to "
    "sort and scroll sideways for more; the player's name stays in view. What each stat means is on the "
    "Stat definitions page in the sidebar."
)

kind = st.radio("Show", ["Skaters", "Goalies"], horizontal=True, label_visibility="collapsed")
skaters = kind == "Skaters"
TABLE = "players" if skaters else "goalies"

season_col, name_col, team_col, position_col, minimum_col = st.columns([1, 2, 2, 2, 3])
season = season_col.selectbox("Season", settings.SEASONS, format_func=settings.season_label)
data = loaders.load_players(season) if skaters else loaders.load_goalies(season)
name = name_col.text_input("Search player", placeholder="Name")
team = team_col.selectbox("Team", [table_view.ALL_TEAMS, *table_view.team_options(data)])
if skaters:
    position = position_col.selectbox("Position", list(table_view.POSITION_FILTERS))
    minimum = minimum_col.slider(
        "Minimum 5v5 minutes", 0, settings.MAX_MIN_MINUTES_5V5, settings.DEFAULT_MIN_MINUTES_5V5, step=50
    )
    rows = table_view.filter_players(data, name, team, position, minimum)
else:
    minimum = minimum_col.slider(
        "Minimum games played", 0, settings.MAX_MIN_GAMES_GOALIE, settings.DEFAULT_MIN_GAMES_GOALIE
    )
    rows = table_view.filter_goalies(data, name, team, minimum)

st.caption(f"{rows['player_id'].nunique():,} {kind.lower()}. TOT is a player's combined row after a trade.")
st.dataframe(table_view.grouped_frame(rows, data, TABLE, name_as_index=True), height=720)

traded = table_view.traded_players(rows)
if traded:
    st.subheader("Traded players by team")
    chosen = st.selectbox(
        "Pick a traded player to see his stats for each team",
        [None, *traded],
        format_func=lambda pid: "Choose a player" if pid is None else traded[pid],
    )
    if chosen is not None:
        st.dataframe(table_view.grouped_frame(table_view.team_breakdown(data, chosen), data, TABLE, name_as_index=True))
