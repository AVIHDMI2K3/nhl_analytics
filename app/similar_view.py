"""The logic behind the Player Similarity Score page, in plain pandas (no Streamlit): which players can be picked, which
matches to show, and how the table is laid out and colored. Kept apart from the page so it can be tested."""

import compare_view
import pandas as pd

# The five categories of the similarity score, in the table's order: the key in the `gap_*` columns, then the name
# shown. What each holds is in CATEGORY_NOTES (the stats themselves are listed in transform/similarity.py).
CATEGORIES = (
    ("scoring", "Scoring"),
    ("shot_share", "Shot share"),
    ("shot_volume", "Shot volume"),
    ("physical", "Physical"),
    ("usage", "Usage"),
)
CATEGORY_NOTES = {
    "Scoring": (
        "goals, assists, points, shots and shooting % per 60, and the player's own attempts, shots and goals per 60"
    ),
    "Shot share": "Corsi %, Fenwick %, shots % and goals % at 5v5, plain and relative to his team",
    "Shot volume": "attempts, unblocked attempts, shots and goals for and against per 60 while he is on the ice at 5v5",
    "Physical": "hits, blocks, takeaways and giveaways per 60",
    "Usage": "time on ice per game",
}
MODE_LABELS = {"same_season": "Same season", "all_seasons": "All seasons"}
DEFAULT_MODE = "same_season"
# The similarity score (0 to 100) is written in a color: red up to 30, amber above 30 up to 60, green above 60. Inside a
# band the shade moves from the first color to the second as the score rises. Each shade keeps enough contrast on both a
# dark and a white page, so the score reads on either theme.
BANDS = (
    (0, 30, (190, 30, 45), (226, 74, 40)),
    (30, 60, (190, 100, 0), (208, 130, 0)),
    (60, 100, (92, 152, 30), (24, 140, 74)),
)
# Only skaters with at least this many minutes of 5v5 ice time in a season have similarity entries (the ranking pool).
POOL_MINUTES = 600


def mode_label(mode):
    """The name of a similarity mode for the page; a mode the page does not know is shown as its own words."""
    return MODE_LABELS.get(mode, mode.replace("_", " ").capitalize())


def mode_options(similarity):
    """The modes the similarity table has, the default first. The page lists whatever the table holds, so a new mode
    (say the last three seasons) needs only a rebuilt table."""
    modes = sorted(similarity["mode"].unique(), key=lambda mode: (mode != DEFAULT_MODE, mode))
    return {mode: mode_label(mode) for mode in modes}


def player_options(percentiles, similarity, season):
    """{player_id: "Name (TEAMS, position)"} for the picker: the players of that season's percentile table who have
    entries in the similarity table. A player below the ranking pool's minimum has none, so he is not listed."""
    entered = set(similarity.loc[similarity["season"] == season, "player_id"])
    return {
        player_id: label
        for player_id, label in compare_view.player_options(percentiles).items()
        if player_id in entered
    }


def matches(similarity, season, player_id, mode):
    """The closest players to one player-season in one mode, rank 1 (the closest) first."""
    chosen = similarity[
        (similarity["season"] == season) & (similarity["player_id"] == player_id) & (similarity["mode"] == mode)
    ]
    return chosen.sort_values("rank", kind="stable").reset_index(drop=True)


def display_table(found, season_label):
    """The table the page shows: rank (as the index), the match's name, season, team and position, the similarity
    score and the gap in each category (smaller is more alike; empty when a category could not be compared)."""
    table = pd.DataFrame(
        {
            "Rank": found["rank"].to_numpy(),
            "Player": found["other_name"].to_numpy(),
            "Season": [season_label(season) for season in found["other_season"]],
            "Team": found["other_team"].to_numpy(),
            "Pos": found["other_position"].to_numpy(),
            "Similarity": found["similarity"].to_numpy(),
            **{label: found[f"gap_{key}"].to_numpy() for key, label in CATEGORIES},
        }
    )
    return table.set_index("Rank")


def similarity_style(value):
    """The CSS for one similarity score: bold text in the color of its band, shaded by where it falls in the band."""
    if value is None or pd.isna(value):
        return ""
    value = min(max(float(value), 0.0), 100.0)
    low, high, start, end = next(band for band in BANDS if value <= band[1])
    share = (value - low) / (high - low)
    red, green, blue = (round(a + (b - a) * share) for a, b in zip(start, end, strict=True))
    return f"color: rgb({red}, {green}, {blue}); font-weight: 700"


def styled(table):
    """The table with the similarity score colored and every number to one decimal (an empty gap shown as a dash).
    Colored by hand: pandas' own gradient needs matplotlib, which the deployed app does not install."""
    numbers = ["Similarity", *(label for _, label in CATEGORIES)]
    return table.style.map(similarity_style, subset=["Similarity"]).format(dict.fromkeys(numbers, "{:.1f}"), na_rep="-")


def chosen_match(found, rows):
    """The match the visitor clicked in the table, or None. `rows` are the clicked row positions Streamlit reports;
    a stale position (the table changed since the click) counts as no choice."""
    if len(rows) != 1 or not 0 <= rows[0] < len(found):
        return None
    row = found.iloc[rows[0]]
    return {"season": int(row["other_season"]), "player_id": int(row["other_player_id"]), "name": row["other_name"]}
