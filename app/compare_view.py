"""The logic behind the Compare page, in plain pandas (no Streamlit or chart code): which players can be paired, and
how two players' percentiles are laid out for the chart and the table. Kept apart from the page so it can be tested."""

import pandas as pd

# The chart's stat groups, top to bottom, with the stats of each in the order they are drawn. Every stat of the
# percentile table is listed here; one that is not still shows, in a group called "Other", so none is dropped.
GROUPS = (
    ("Scoring", ("goals_per_60", "assists_per_60", "points_per_60", "shots_per_60", "shooting_pct")),
    ("Individual shooting (5v5)", ("ig_per_60", "isf_per_60", "icf_per_60")),
    (
        "Shot attempts (5v5)",
        ("cf_per_60", "ca_per_60", "cf_pct", "cf_pct_rel", "ff_per_60", "fa_per_60", "ff_pct", "ff_pct_rel"),
    ),
    ("Shots on goal (5v5)", ("sf_per_60", "sa_per_60", "sf_pct", "sf_pct_rel")),
    ("Goals (5v5)", ("gf_per_60", "ga_per_60", "gf_pct", "gf_pct_rel")),
    ("Without the puck", ("hits_per_60", "blocks_per_60", "takeaways_per_60", "giveaways_per_60")),
    ("Ice time", ("toi_per_game",)),
)
OTHER = "Other"
STAT_GROUP = {stat: group for group, stats in GROUPS for stat in stats}
STAT_RANK = {stat: rank for rank, stat in enumerate(stat for _, stats in GROUPS for stat in stats)}
POSITION_GROUP_NAMES = {"F": "forwards", "D": "defensemen"}
PLAYER_COLUMNS = ["player_id", "name", "position", "position_group", "teams", "minutes_5v5", "in_pool"]


def group_of(stat):
    """The chart group a stat is drawn under."""
    return STAT_GROUP.get(stat, OTHER)


def stat_order(stats):
    """`stats` sorted into the chart's order: group by group as in GROUPS, then any stat not listed there."""
    return sorted(stats, key=lambda stat: (STAT_RANK.get(stat, len(STAT_RANK)), stat))


def one_per_player(percentiles):
    """One row per player of a season's percentile table (it has one row per player and stat), by name."""
    return percentiles.drop_duplicates("player_id")[PLAYER_COLUMNS].sort_values("name", kind="stable")


def player_options(percentiles, position_group=None):
    """{player_id: "Name (TEAM, TEAM, position)"} for the pickers, by name. With `position_group` ("F" or "D") only
    players of that group: a forward's percentiles are ranked among forwards, so they cannot be set against a
    defenseman's."""
    players = one_per_player(percentiles)
    if position_group is not None:
        players = players[players["position_group"] == position_group]
    return {
        int(player_id): f"{name} ({teams}, {position})"
        for player_id, name, teams, position in zip(
            players["player_id"], players["name"], players["teams"], players["position"], strict=True
        )
    }


def position_group_of(percentiles, player_id):
    """ "F" or "D" for a player of the table, None when he is not in it."""
    found = percentiles.loc[percentiles["player_id"] == player_id, "position_group"]
    return found.iloc[0] if len(found) else None


def distinct_labels(first, second):
    """The two names for the chart. When they are the same (two players with one name, in one season) the second
    gets a "(2)" so the chart and table can tell them apart."""
    return first, (second if second != first else f"{second} (2)")


def comparison(first_table, first_id, first_label, second_table, second_id, second_label):
    """Both players' rows (one per stat) in one frame, in the chart's order, the first player before the second for
    each stat. Each player is looked up in his own season's table. Columns: group, stat, label, order, player, value,
    percentile (empty when he has no value for the stat), in_pool."""
    parts = []
    for table, player_id, who in ((first_table, first_id, first_label), (second_table, second_id, second_label)):
        rows = table.loc[table["player_id"] == player_id, ["stat", "label", "value", "percentile", "in_pool"]].copy()
        rows["player"] = who
        parts.append(rows)
    frame = pd.concat(parts, ignore_index=True)
    order = {stat: rank for rank, stat in enumerate(stat_order(frame["stat"].unique()))}
    frame["group"] = frame["stat"].map(group_of)
    frame["order"] = frame["stat"].map(order)
    columns = ["group", "stat", "label", "order", "player", "value", "percentile", "in_pool"]
    return frame.sort_values("order", kind="stable")[columns].reset_index(drop=True)


def players_outside_pool(frame):
    """The players of a `comparison` frame who are below the ranking pool's minimum 5v5 time. Their percentiles are
    still ranked against the pool but rest on little ice time."""
    in_pool = frame.groupby("player", sort=False)["in_pool"].first()
    return [player for player, inside in in_pool.items() if not inside]


def side_by_side(frame, first_label, second_label):
    """The table under the chart: one row per stat, grouped as in the chart, with each player's value and percentile."""
    first = frame[frame["player"] == first_label].set_index("stat")
    second = frame[frame["player"] == second_label].set_index("stat")
    stats = list(dict.fromkeys(frame["stat"]))
    data = {}
    for who, rows in ((first_label, first), (second_label, second)):
        data[(who, "Value")] = rows["value"].reindex(stats).round(2).to_numpy()
        data[(who, "Percentile")] = rows["percentile"].reindex(stats).round(1).to_numpy()
    index = pd.MultiIndex.from_arrays(
        [[group_of(stat) for stat in stats], first["label"].reindex(stats).to_numpy()], names=["Group", "Stat"]
    )
    return pd.DataFrame(data, index=index)
