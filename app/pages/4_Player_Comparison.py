"""Player Comparison page: two skaters side by side, each stat a percentile among his position group that season."""

import compare_chart
import compare_view
import loaders
import streamlit as st
from shared import settings

# The ranking pool's minimum 5v5 minutes (build_player_percentiles.py --min-minutes). Only used in the note below.
POOL_MINUTES = 600
ROW_HEIGHT = 35  # pixels of one table row in st.dataframe

st.set_page_config(page_title="Player Comparison - NHL Analytics", layout="wide")
st.title("Player Comparison")
st.caption(
    "Pick two skaters of the same position group. Each stat is a percentile: how the player ranks among forwards (or "
    "among defensemen) in his season, where 100 is the best and 50 the middle. Each player has his own season, so "
    "you can compare two players in one season, or one player in two different seasons."
)


def pick(title, key, position_group=None):
    """One player's pickers: a season, then a player of that season (type to search). Returns the season, that
    season's percentile table and the player's id, which is None until one is chosen."""
    st.subheader(title)
    season = st.selectbox("Season", settings.SEASONS, format_func=settings.season_label, key=f"season_{key}")
    table = loaders.load_percentiles(season)
    options = compare_view.player_options(table, position_group)
    player = st.selectbox(
        "Player", list(options), format_func=options.get, index=None, placeholder="Type a name", key=f"player_{key}"
    )
    return season, table, player


def name_of(table, player_id):
    return compare_view.one_per_player(table).set_index("player_id").loc[player_id, "name"]


left, right = st.columns(2)
with left:
    season_a, table_a, player_a = pick("First player", "a")
group = compare_view.position_group_of(table_a, player_a) if player_a is not None else None
with right:
    season_b, table_b, player_b = pick("Second player", "b", group)
if group is not None:
    st.caption(f"The second player's list only has {compare_view.POSITION_GROUP_NAMES[group]}, like the first.")

if player_a is None or player_b is None:
    st.info("Choose a player on each side to see the comparison.")
    st.stop()
if (player_a, season_a) == (player_b, season_b):
    st.warning("Choose two different players, or the same player in two different seasons.")
    st.stop()

label_a = f"{name_of(table_a, player_a)} ({settings.season_label(season_a)})"
label_b = f"{name_of(table_b, player_b)} ({settings.season_label(season_b)})"
label_a, label_b = compare_view.distinct_labels(label_a, label_b)
frame = compare_view.comparison(table_a, player_a, label_a, table_b, player_b, label_b)

outside = compare_view.players_outside_pool(frame)
if outside:
    st.warning(
        f"{' and '.join(outside)}: under {POOL_MINUTES} minutes of 5v5 ice time that season. The percentile ranks "
        "him against players who played more, but on little ice time, so it can swing a lot."
    )

st.altair_chart(compare_chart.paired_dots(frame, label_a, label_b, compare_view.POSITION_GROUP_NAMES[group]))
st.caption(
    "Right is better. Where fewer is better (shot attempts against, goals against, giveaways) the percentile is "
    "flipped, so a dot far to the right still means better. A missing dot means no value for that stat, for example "
    "a player with no shots. Hover over a dot for the exact value."
)

st.subheader("The numbers")
numbers = compare_view.side_by_side(frame, label_a, label_b)
# Fixed decimals (percentiles to one, values to two), so a column does not mix 11 with 10.1; a missing value is a dash.
formats = {column: "{:.1f}" if column[1] == "Percentile" else "{:.2f}" for column in numbers.columns}
# Sized to its content: two header rows plus one row per stat, so no empty strip is left under the table.
st.dataframe(numbers.style.format(formats, na_rep="-"), height=ROW_HEIGHT * (len(numbers) + 2) + 2)
