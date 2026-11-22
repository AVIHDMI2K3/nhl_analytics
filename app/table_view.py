"""The logic behind the app's tables, in plain pandas (no Streamlit): which rows to show, and how to lay the chosen
columns out under their group labels. Kept apart from the pages so it can be tested."""

import pandas as pd
from shared import labels

ALL_TEAMS = "All teams"
POSITION_FILTERS = {"All skaters": None, "Forwards": ("C", "L", "R"), "Defensemen": ("D",)}
DEFAULT_DECIMALS = 1
DECIMALS = {"points_pct": 3}
# Stored as percentages (91.5) and shown the way hockey writes them: a fraction with three decimals (0.915).
FRACTION_COLUMNS = ("save_pct", "even_strength_save_pct", "power_play_save_pct", "shorthanded_save_pct")


def shown_rows(df):
    """One row per player: his combined row if he changed teams, else his only row. His rows for each single
    team are left out (a traded player's `teams` lists more than the one team in `team`)."""
    return df[(df["kind"] == "total") | (df["teams"] == df["team"])]


def team_options(df):
    """Team abbreviations in the table, alphabetical."""
    return sorted(df.loc[df["kind"] == "team", "team"].dropna().unique())


def traded_players(rows):
    """The traded players among `rows`: {player_id: "Name (TEAM, TEAM)"} in the order of the rows."""
    total = rows[rows["kind"] == "total"]
    return {pid: f"{name} ({teams})" for pid, name, teams in zip(total["player_id"], total["name"], total["teams"])}


def team_breakdown(df, player_id):
    """A traded player's combined (TOT) row followed by his row for each team, the team he played most games for
    first."""
    mine = df[df["player_id"] == player_id]
    team_rows = mine[mine["kind"] == "team"].sort_values("games_played", ascending=False, kind="stable")
    return pd.concat([mine[mine["kind"] == "total"], team_rows])


def filter_players(df, name="", team=ALL_TEAMS, position="All skaters", min_minutes=0):
    """Rows to show after the page's filters. A traded player is found under every team he played for."""
    rows = shown_rows(df)
    if team != ALL_TEAMS:
        rows = rows[rows["teams"].fillna("").str.contains(team, regex=False)]
    codes = POSITION_FILTERS[position]
    if codes is not None:
        rows = rows[rows["position"].isin(codes)]
    if name.strip():
        rows = rows[rows["name"].str.contains(name.strip(), case=False, regex=False)]
    return rows[rows["minutes_5v5"].fillna(0) >= min_minutes]


def filter_goalies(df, name="", team=ALL_TEAMS, min_games=0):
    """Goalie rows to show after the page's filters; a traded goalie is found under every team he played for."""
    rows = shown_rows(df)
    if team != ALL_TEAMS:
        rows = rows[rows["teams"].fillna("").str.contains(team, regex=False)]
    if name.strip():
        rows = rows[rows["name"].str.contains(name.strip(), case=False, regex=False)]
    return rows[rows["games_played"].fillna(0) >= min_games]


def all_columns(table):
    """Every stat column the table shows, in the order of its groups."""
    return [column for _, columns in labels.GROUPS[table] for column in columns]


def _is_whole(series):
    return bool((series.dropna() % 1 == 0).all())


def _decimals(column, full):
    """Decimals for a non-whole column: set by name, 3 for ratios kept between 0 and 1 (save percentage), else 1."""
    if column in DECIMALS:
        return DECIMALS[column]
    return 3 if full[column].abs().max() <= 1 else DEFAULT_DECIMALS


def grouped_frame(rows, full, table, columns=None, name_as_index=False):
    """The table as shown: the fixed columns, then `columns` (default: all of the table's), each under a
    (group, label) header. With `name_as_index` the first fixed column becomes the row index, which the table keeps
    in view while scrolling sideways.

    `full` is the whole season's table. Whether a column shows whole numbers or one decimal is decided from it, not from
    `rows`, so the same column looks the same however the rows are filtered. Seconds are shown as minutes."""
    group_of = {column: group for group, group_columns in labels.GROUPS[table] for column in group_columns}
    columns = all_columns(table) if columns is None else columns
    shown = {}
    for column in labels.FIXED[table]:
        shown[("", labels.label(column))] = rows[column].reset_index(drop=True)
    for column in columns:
        values = rows[column].reset_index(drop=True)
        if column in labels.SECONDS_COLUMNS:
            values = (values / 60).round(DEFAULT_DECIMALS)
        elif column in FRACTION_COLUMNS:
            values = (values / 100).round(3)
        elif _is_whole(full[column]):
            values = values.astype("Int64")
        else:
            values = values.round(_decimals(column, full))
        shown[(group_of[column], labels.label(column))] = values
    frame = pd.DataFrame(shown)
    if name_as_index:
        frame = frame.set_index(frame.columns[0])
        frame.index.name = labels.label(labels.FIXED[table][0])
    return frame


def definitions(table):
    """[(group, DataFrame of Stat and Meaning)] for every column the table shows, in display order. The row's own
    columns (name, team) come first under "Row"."""
    row = [(labels.label(c), labels.description(table, c)) for c in labels.FIXED[table]]
    groups = [("Row", row)] + [
        (group, [(labels.label(c), labels.description(table, c)) for c in columns])
        for group, columns in labels.GROUPS[table]
    ]
    return [(group, pd.DataFrame(items, columns=["Stat", "Meaning"])) for group, items in groups]
