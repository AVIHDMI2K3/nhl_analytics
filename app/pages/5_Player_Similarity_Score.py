"""Player Similarity Score page: the skaters whose season looks most like the chosen player's, by percentile
profile. Clicking a match offers a button that opens that pair in Player Comparison."""

import compare_view
import loaders
import similar_view
import streamlit as st
from shared import settings

ROW_HEIGHT = 35  # pixels of one table row in st.dataframe

st.set_page_config(page_title="Player Similarity Score - NHL Analytics", layout="wide")
st.title("Player Similarity Score")
st.caption(
    "Pick a skater and see the 15 players whose season looks most like his. Each stat is turned into a percentile "
    "among forwards (or among defensemen) in its season, and two players are alike when their percentiles are close "
    "across five categories that count equally."
)

similarity = loaders.load_similarity()
modes = similar_view.mode_options(similarity)

season_column, player_column, mode_column = st.columns([1, 3, 3])
season = season_column.selectbox("Season", settings.SEASONS, format_func=settings.season_label, key="season")
options = similar_view.player_options(loaders.load_percentiles(season), similarity, season)
player = player_column.selectbox(
    "Player", list(options), format_func=options.get, index=None, placeholder="Type a name", key="player"
)
mode = mode_column.radio("Look for matches in", list(modes), format_func=modes.get, horizontal=True, key="mode")
st.caption(
    f"Only skaters with at least {similar_view.POOL_MINUTES} minutes of 5v5 ice time in a season are listed: with "
    "less, their percentiles rest on too little play to compare."
)

if player is None:
    st.info("Choose a player to see his closest matches.")
    st.stop()

found = similar_view.matches(similarity, season, player, mode)
if found.empty:
    st.warning("No matches were found for this player.")
    st.stop()

pool_name = compare_view.POSITION_GROUP_NAMES[found["position_group"].iloc[0]]
if mode == "same_season":
    st.subheader(f"The {pool_name} most like {found['name'].iloc[0]} in {settings.season_label(season)}")
else:
    st.subheader(f"The {pool_name} most like {found['name'].iloc[0]} ({settings.season_label(season)}) in any season")
    st.caption(
        "Percentiles are ranks within each season, so a match from another season is someone who ranked the same way "
        "in his own year. A player's own other seasons are never matches."
    )

table = similar_view.display_table(found, settings.season_label)
event = st.dataframe(
    similar_view.styled(table),
    height=ROW_HEIGHT * (len(table) + 1) + 2,
    on_select="rerun",
    selection_mode="single-row",
    key="matches",
)
st.caption(
    "**Similarity** is 100 minus the average gap between the two players' percentiles across five categories, so 100 "
    "is identical and 90 means about 10 percentile points apart. The five columns after it are the gap in each "
    "category: smaller means more alike. **TOT** is a player who changed teams that season."
)

match = similar_view.chosen_match(found, event.selection.rows)
if match is None:
    st.caption("Click a row to compare that player with " + found["name"].iloc[0] + ".")
elif st.button(f"Compare {found['name'].iloc[0]} with {match['name']}", type="primary", key="compare"):
    # The Player Comparison page reads these keys for its two pickers, so it opens with both players chosen.
    st.session_state.update(
        {"season_a": season, "player_a": player, "season_b": match["season"], "player_b": match["player_id"]}
    )
    st.switch_page("pages/4_Player_Comparison.py")
with st.expander("What the five categories are"):
    for label, note in similar_view.CATEGORY_NOTES.items():
        st.markdown(f"- **{label}**: {note}")
