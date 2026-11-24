"""Lines and Pairs page: every forward line or defense pair with enough 5v5 ice time together, in one table."""

import loaders
import streamlit as st
import table_view
from shared import settings

TABLE = "lines"

st.set_page_config(page_title="Lines and Pairs - NHL Analytics", layout="wide")
st.title("Lines and Pairs")
st.caption(
    "Forward lines and defense pairs at 5v5, with stat groups labeled across the top. Click a column to sort and "
    "scroll sideways for more. A line's order (left wing, center, right wing) is a best guess when it lists two or "
    "more centers. What each stat means is on the Stat definitions page in the sidebar."
)

kind = st.radio("Show", list(table_view.UNIT_TYPES), horizontal=True, label_visibility="collapsed")
season_col, team_col, name_col, minimum_col = st.columns([1, 2, 2, 4])
season = season_col.selectbox("Season", settings.SEASONS, format_func=settings.season_label)
units = loaders.load_units(season)
team = team_col.selectbox("Team", [table_view.ALL_TEAMS, *table_view.unit_team_options(units)])
name = name_col.text_input("Search player", placeholder="Name")
top = table_view.slider_max(units["minutes"], 25)
minimum = minimum_col.slider(
    "Minimum 5v5 minutes together", 0, top, min(settings.DEFAULT_MIN_MINUTES_UNIT, top), step=25
)

rows = table_view.filter_units(units, table_view.UNIT_TYPES[kind], name, team, minimum)
st.caption(
    f"{len(rows):,} {kind.lower()} with at least {minimum} minutes together. Combinations with under "
    f"{units['minutes'].min():.0f} minutes together are not in the data, because most of them are one-off "
    "pairings. A player traded mid-season may therefore show lines for only one of his teams."
)
frame = table_view.grouped_frame(rows, units, TABLE, name_as_index=True)
frame.index.name = "Line" if kind == "Forward lines" else "Pair"
st.dataframe(frame, height=720)
