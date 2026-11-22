"""Home page. Run the app from the repo root with:  streamlit run app/Home.py"""

import streamlit as st
from shared import settings

st.set_page_config(page_title="NHL Analytics", layout="wide")

st.title("Advanced NHL stats, explained for fans")
st.write(
    "Look up any skater or goalie, see which lines and defense pairs worked, compare two players side by side, "
    "and find the players who play most like a favorite. Three regular seasons, built from the NHL's own "
    "play-by-play and shift data."
)
st.page_link("pages/1_Players.py", label="Browse players", icon=":material/arrow_forward:")
st.page_link("pages/2_Stat_Definitions.py", label="What do the stats mean?", icon=":material/help:")

st.subheader("What you can do here")
cards = [
    ("Players", "Basic and advanced stats for every skater, with power-play, penalty-kill and faceoff columns."),
    (
        "Lines and Pairs",
        "Every forward line and defense pair with enough ice time, with shot share, goals and zone starts.",
    ),
    ("Compare", "Two players on a pizza chart, each stat ranked against the players of his position that season."),
    ("Similar Players", "The closest players to the one you pick, in the same season or across all three."),
    ("Teams", "Team records, shot share, power play and penalty kill, all in one table."),
]
built = {"Players"}
for column, (title, text) in zip(st.columns(len(cards)), cards, strict=True):
    with column, st.container(border=True):
        st.markdown(f"**{title}**" + ("" if title in built else " (coming soon)"))
        st.caption(text)

st.subheader("How the numbers were checked")
st.write(
    "The stats are calculated here from the NHL's play-by-play and shift reports, then compared with Natural Stat "
    "Trick, a long-standing public source. Natural Stat Trick's data is used only for checking and is not shown "
    "in the app."
)
checks = [
    ("0.01%", "The most that league-wide shot attempts differ from Natural Stat Trick's, for skaters in every season."),
    ("95-99%", "Of skaters have the same on-ice goals as Natural Stat Trick, depending on the season."),
    (
        "98.6-99.0%",
        "Of 5v5 time has a forward line and a defense pair on the ice. The rest is time with an unusual mix "
        "of forwards and defensemen.",
    ),
]
for column, (number, text) in zip(st.columns(len(checks)), checks, strict=True):
    with column, st.container(border=True):
        st.markdown(f"### {number}")
        st.caption(text)

left, right = st.columns(2)
with left:
    st.subheader("Terms you will see")
    st.markdown(
        "- **5v5**: five skaters and a goalie on each side, the most common situation in a game.\n"
        "- **CF% (Corsi)**: the share of all shot attempts, including blocked and missed ones, that his team takes "
        "while he is on the ice. Above 50% means his team had the puck more.\n"
        "- **Relative CF%**: his team's CF% with him on the ice minus without him.\n"
        "- **OZ start%**: the share of a line's faceoffs that began in the offensive zone, not counting "
        "neutral-zone ones.\n"
        "- **Percentile**: how a player ranks among his position group that season. 90 means better than 90% of them."
    )
with right:
    st.subheader("Things to keep in mind")
    notes = (
        "- Hits, blocks, takeaways and giveaways are counted by each arena's scorers, so they vary from rink to rink.\n"
        "- A percentile shows where a player ranks, not how far ahead he is.\n"
        "- A line's order (left wing, center, right wing) is a best guess when it has two or more listed centers.\n"
        "- Penalty-shot goals are left out of shot-attempt counts, which causes a small gap in some team totals.\n"
    )
    if settings.DATA_NOTES_URL:
        notes += f"- The full list of limits is in the [data notes]({settings.DATA_NOTES_URL})."
    st.markdown(notes)

footer = "A personal portfolio project by Avi Sharma. Built with Python and Streamlit"
footer += f"; [code on GitHub]({settings.GITHUB_URL})." if settings.GITHUB_URL else "."
st.caption(footer + " Not affiliated with the NHL or any team.")
