"""Stat definitions page: what every column in the app's tables means, grouped the way the tables are."""

import streamlit as st
import table_view

TABLES = {"Skaters": "players", "Goalies": "goalies", "Teams": "teams", "Lines and pairs": "lines"}

st.set_page_config(page_title="Stat definitions - NHL Analytics", layout="wide")
st.title("Stat definitions")
st.caption("What each column means, in the same groups as the tables.")

with st.container(border=True):
    st.markdown(
        "- **5v5** means five skaters and a goalie on each side, the best view of how a player drives play.\n"
        "- **CF%** and similar shares: above 50% means the team had more of the shot attempts (or shots, or goals) "
        "while he was on the ice.\n"
        "- **Per 60** rates put players with different ice time on the same footing.\n"
        "- **TOT** is a player's combined row after a trade.\n"
        "- Save percentages are shown as fractions (.915). Every other percentage is out of 100."
    )

choice = st.radio("Table", list(TABLES), horizontal=True, label_visibility="collapsed")
search = st.text_input("Search", placeholder="Search a stat, such as CF% or power play").strip().lower()

shown = 0
for group, items in table_view.definitions(TABLES[choice]):
    if search:
        items = items[
            items["Stat"].str.lower().str.contains(search, regex=False)
            | items["Meaning"].str.lower().str.contains(search, regex=False)
        ]
    if items.empty:
        continue
    shown += len(items)
    st.subheader(group)
    st.dataframe(items, hide_index=True, width="stretch")
if not shown:
    st.info("No stat matches that search.")
