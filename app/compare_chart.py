"""The Compare page's chart: two players as paired dots, one row per stat, on a 0-100 percentile scale. Built with
Altair, which comes with Streamlit. One small chart per stat group, stacked, so each group's title sits over its rows
and the rows stay evenly spaced."""

import re

import altair as alt
import pandas as pd

FIRST_COLOR = "#2a6f97"
SECOND_COLOR = "#d1495b"
SHAPES = ["circle", "diamond"]  # a second cue besides color
ROW_HEIGHT = 26
PLOT_WIDTH = 560
SCALE = alt.Scale(domain=[0, 100], nice=False)


def chart_label(label):
    """A stat's label for the axis: without the '(5v5)' or '(fewer is better)' note, which the group title and the
    chart's caption already say. The hover text keeps the full label."""
    return re.sub(r"\s*\((5v5[^)]*|fewer is better)\)$", "", label)


def paired_dots(frame, first_label, second_label, pool_name):
    """The chart for a `compare_view.comparison` frame. `pool_name` ("forwards" or "defensemen") goes in the axis
    title. A stat with no percentile for a player is left without a dot (and without the line between the dots)."""
    players = [first_label, second_label]
    legend = alt.Legend(title=None, orient="top", symbolSize=140)
    color = alt.Color("player:N", scale=alt.Scale(domain=players, range=[FIRST_COLOR, SECOND_COLOR]), legend=legend)
    shape = alt.Shape("player:N", scale=alt.Scale(domain=players, range=SHAPES), legend=legend)
    groups = list(dict.fromkeys(frame["group"]))
    charts = [
        _group_chart(frame[frame["group"] == group], group, players, color, shape, pool_name, index == len(groups) - 1)
        for index, group in enumerate(groups)
    ]
    return alt.vconcat(*charts, spacing=16).configure_view(stroke=None)


def _group_chart(part, group, players, color, shape, pool_name, last):
    """One group's rows: the 50 line, the line between each pair of dots, and the dots. Only the last group's chart
    labels the bottom axis."""
    part = part.assign(stat_row=part["label"].map(chart_label))
    rows = list(dict.fromkeys(part["stat_row"]))
    x = alt.X(
        "percentile:Q",
        scale=SCALE,
        axis=alt.Axis(
            values=[0, 25, 50, 75, 100],
            labels=last,
            ticks=last,
            title=f"Percentile among {pool_name} of the same season (higher is better)" if last else None,
        ),
    )
    y = alt.Y("stat_row:N", sort=rows, title=None, axis=alt.Axis(ticks=False, domain=False, labelLimit=320))

    wide = part.pivot(index="stat_row", columns="player", values="percentile").reindex(index=rows, columns=players)
    links = pd.DataFrame(
        {
            "stat_row": rows,
            "percentile": wide.min(axis=1, skipna=False).to_numpy(),
            "percentile2": wide.max(axis=1, skipna=False).to_numpy(),
        }
    )

    middle = alt.Chart(pd.DataFrame({"percentile": [50]})).mark_rule(strokeDash=[4, 4], color="#999999").encode(x=x)
    link = alt.Chart(links).mark_rule(color="#b8b8b8", strokeWidth=3).encode(x=x, x2="percentile2:Q", y=y)
    dots = (
        alt.Chart(part)
        .mark_point(filled=True, size=150, opacity=1)
        .encode(
            x=x,
            y=y,
            color=color,
            shape=shape,
            tooltip=[
                alt.Tooltip("player:N", title="Player"),
                alt.Tooltip("label:N", title="Stat"),
                alt.Tooltip("value:Q", title="Value", format=".2f"),
                alt.Tooltip("percentile:Q", title="Percentile", format=".1f"),
            ],
        )
    )
    title = alt.TitleParams(group.upper(), anchor="start", fontSize=11, fontWeight="bold", color="#777777", offset=8)
    return alt.layer(middle, link, dots).properties(width=PLOT_WIDTH, height=ROW_HEIGHT * len(rows), title=title)
