"""Tests for app/compare_view.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import compare_view as cv  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

# The 29 stats of player_season_percentiles.
ALL_STATS = {
    "assists_per_60",
    "blocks_per_60",
    "ca_per_60",
    "cf_pct",
    "cf_pct_rel",
    "cf_per_60",
    "fa_per_60",
    "ff_pct",
    "ff_pct_rel",
    "ff_per_60",
    "ga_per_60",
    "gf_pct",
    "gf_pct_rel",
    "gf_per_60",
    "giveaways_per_60",
    "goals_per_60",
    "hits_per_60",
    "icf_per_60",
    "ig_per_60",
    "isf_per_60",
    "points_per_60",
    "sa_per_60",
    "sf_pct",
    "sf_pct_rel",
    "sf_per_60",
    "shooting_pct",
    "shots_per_60",
    "takeaways_per_60",
    "toi_per_game",
}
STATS = ["ca_per_60", "goals_per_60", "toi_per_game"]  # deliberately out of the chart's order


def player_rows(
    player_id, name, group="F", position="C", teams="TOR", in_pool=True, values=(70.0, 1.2, 17.5), pct=None
):
    pct = pct if pct is not None else (90.0, 80.0, 70.0)
    return [
        {
            "player_id": player_id,
            "name": name,
            "position": position,
            "position_group": group,
            "teams": teams,
            "minutes_5v5": 900.0 if in_pool else 200.0,
            "in_pool": in_pool,
            "stat": stat,
            "label": f"{stat} label",
            "value": value,
            "percentile": percentile,
        }
        for stat, value, percentile in zip(STATS, values, pct, strict=True)
    ]


@pytest.fixture
def table():
    return pd.DataFrame(
        player_rows(1, "Mitch Marner", position="R", teams="TOR")
        + player_rows(2, "Auston Matthews", position="C", teams="TOR", values=(60.0, 1.6, 19.0), pct=(70.0, 99.0, 85.0))
        + player_rows(3, "Quinn Hughes", group="D", position="D", teams="VAN, MIN")
        + player_rows(4, "Fringe Winger", in_pool=False, teams="CGY")
    )


def test_groups_cover_every_percentile_stat_once():
    listed = [stat for _, stats in cv.GROUPS for stat in stats]
    assert len(listed) == len(set(listed))
    assert set(listed) == ALL_STATS


def test_group_of_known_and_unknown_stats():
    assert cv.group_of("goals_per_60") == "Scoring"
    assert cv.group_of("ca_per_60") == "Shot attempts (5v5)"
    assert cv.group_of("something_new") == cv.OTHER


def test_stat_order_follows_the_groups_and_puts_unlisted_stats_last():
    stats = ["toi_per_game", "zzz_new", "ca_per_60", "goals_per_60", "aaa_new"]
    assert cv.stat_order(stats) == ["goals_per_60", "ca_per_60", "toi_per_game", "aaa_new", "zzz_new"]


def test_one_per_player_is_sorted_by_name(table):
    names = list(cv.one_per_player(table)["name"])
    assert names == ["Auston Matthews", "Fringe Winger", "Mitch Marner", "Quinn Hughes"]


def test_player_options_label_players_and_can_be_limited_to_a_position_group(table):
    everyone = cv.player_options(table)
    assert everyone[3] == "Quinn Hughes (VAN, MIN, D)"
    assert list(everyone) == [2, 4, 1, 3]
    assert list(cv.player_options(table, "F")) == [2, 4, 1]
    assert list(cv.player_options(table, "D")) == [3]


def test_position_group_of(table):
    assert cv.position_group_of(table, 3) == "D"
    assert cv.position_group_of(table, 1) == "F"
    assert cv.position_group_of(table, 999) is None


def test_distinct_labels():
    assert cv.distinct_labels("A (2025-26)", "B (2025-26)") == ("A (2025-26)", "B (2025-26)")
    assert cv.distinct_labels("A (2025-26)", "A (2025-26)") == ("A (2025-26)", "A (2025-26) (2)")


def test_comparison_has_both_players_in_the_charts_order(table):
    frame = cv.comparison(table, 1, "Marner", table, 2, "Matthews")
    assert list(frame.columns) == ["group", "stat", "label", "order", "player", "value", "percentile", "in_pool"]
    assert len(frame) == 6
    assert list(frame["stat"]) == ["goals_per_60"] * 2 + ["ca_per_60"] * 2 + ["toi_per_game"] * 2
    assert list(frame["player"]) == ["Marner", "Matthews"] * 3
    assert list(frame["group"].unique()) == ["Scoring", "Shot attempts (5v5)", "Ice time"]
    goals = frame[frame["stat"] == "goals_per_60"]
    assert list(goals["percentile"]) == [80.0, 99.0]


def test_comparison_looks_each_player_up_in_his_own_seasons_table(table):
    other_season = table.copy()
    other_season["percentile"] = 10.0
    frame = cv.comparison(table, 1, "Marner 2025", other_season, 1, "Marner 2023")
    assert set(frame[frame["player"] == "Marner 2025"]["percentile"]) == {90.0, 80.0, 70.0}
    assert set(frame[frame["player"] == "Marner 2023"]["percentile"]) == {10.0}


def test_comparison_keeps_a_stat_with_no_percentile(table):
    table.loc[(table["player_id"] == 1) & (table["stat"] == "goals_per_60"), "percentile"] = float("nan")
    frame = cv.comparison(table, 1, "Marner", table, 2, "Matthews")
    missing = frame[(frame["player"] == "Marner") & (frame["stat"] == "goals_per_60")]
    assert len(missing) == 1
    assert missing["percentile"].isna().all()


def test_players_outside_pool(table):
    frame = cv.comparison(table, 1, "Marner", table, 4, "Fringe")
    assert cv.players_outside_pool(frame) == ["Fringe"]
    assert cv.players_outside_pool(cv.comparison(table, 1, "Marner", table, 2, "Matthews")) == []


def test_side_by_side_has_a_row_per_stat_under_its_group(table):
    frame = cv.comparison(table, 1, "Marner", table, 2, "Matthews")
    wide = cv.side_by_side(frame, "Marner", "Matthews")
    assert list(wide.index.names) == ["Group", "Stat"]
    assert list(wide.index.get_level_values("Group")) == ["Scoring", "Shot attempts (5v5)", "Ice time"]
    assert list(wide.columns) == [
        ("Marner", "Value"),
        ("Marner", "Percentile"),
        ("Matthews", "Value"),
        ("Matthews", "Percentile"),
    ]
    assert wide.loc[("Scoring", "goals_per_60 label"), ("Matthews", "Value")] == 1.6
    assert wide.loc[("Scoring", "goals_per_60 label"), ("Marner", "Percentile")] == 80.0
