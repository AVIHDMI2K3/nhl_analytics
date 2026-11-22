"""Tests for src/nhl_pipeline/transform/similarity.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))

import pytest  # noqa: E402
import similarity as sm  # noqa: E402
from percentiles import STATS_BY_KEY  # noqa: E402

CATS = {"big": ["a", "b", "c", "d"], "small": ["e"]}


def entry(season, player_id, group="F", name=None, **percentiles):
    return {
        "key": (season, player_id),
        "season": season,
        "player_id": player_id,
        "name": name or f"P{player_id}",
        "team": "TOR",
        "position": "C" if group == "F" else "D",
        "group": group,
        "percentiles": percentiles,
    }


FULL = dict(a=50, b=50, c=50, d=50, e=50)


def test_the_categories_cover_every_catalog_stat_exactly_once():
    listed = [stat for stats in sm.CATEGORIES.values() for stat in stats]
    assert sorted(listed) == sorted(STATS_BY_KEY) and len(listed) == len(set(listed))


def test_identical_entries_are_100_and_the_score_is_100_minus_the_percentile_gap():
    gaps = sm.category_gaps(FULL, dict(FULL), CATS)
    assert sm.similarity(gaps) == 100
    shifted = {k: v + 10 for k, v in FULL.items()}
    assert sm.similarity(sm.category_gaps(FULL, shifted, CATS)) == pytest.approx(90)


def test_every_category_counts_the_same_however_many_stats_it_has():
    big_differs = dict(FULL, a=100, b=100, c=100, d=100)  # 4 stats of the big category differ by 50
    small_differs = dict(FULL, e=100)  # the only stat of the small category differs by 50
    assert sm.similarity(sm.category_gaps(FULL, big_differs, CATS)) == pytest.approx(
        sm.similarity(sm.category_gaps(FULL, small_differs, CATS))
    )


def test_missing_stats_are_left_out_and_a_category_without_any_is_skipped():
    gaps = sm.category_gaps(dict(a=10, b=10, e=40), dict(a=20, c=70, e=40), CATS)
    assert gaps == {"big": pytest.approx(10), "small": 0}
    gaps = sm.category_gaps(dict(a=10), dict(e=40), CATS)
    assert gaps == {"big": None, "small": None} and sm.similarity(gaps) is None


def test_neighbors_are_ranked_by_similarity_kept_to_the_group_and_never_include_the_players_own_seasons():
    entries = [
        entry(2024, 1, **FULL),
        entry(2024, 2, **dict(FULL, a=60)),
        entry(2024, 3, **dict(FULL, a=90)),
        entry(2023, 1, **dict(FULL, a=51)),
        entry(2023, 4, **dict(FULL, a=52)),
        entry(2024, 9, group="D", **FULL),
    ]
    rows = sm.nearest(entries, top_n=5, categories=CATS)
    mine = [r for r in rows if (r["season"], r["player_id"]) == (2024, 1)]
    same = [r for r in mine if r["mode"] == "same_season"]
    every = [r for r in mine if r["mode"] == "all_seasons"]
    assert [(r["other_player_id"], r["rank"]) for r in same] == [(2, 1), (3, 2)]
    assert [(r["other_season"], r["other_player_id"]) for r in every] == [(2023, 4), (2024, 2), (2024, 3)]
    assert all(r["other_player_id"] not in (1, 9) for r in mine)  # not himself in another season, not a defenseman
    assert all(set(r) >= {"gap_big", "gap_small", "similarity"} for r in mine)
    assert every[0]["similarity"] > every[-1]["similarity"]


def test_top_n_limits_each_mode_and_a_player_is_never_his_own_neighbor():
    entries = [entry(2024, i, **dict(FULL, a=50 + i)) for i in range(1, 6)]
    rows = sm.nearest(entries, top_n=2, categories=CATS)
    assert len(rows) == 5 * 2 * 2
    assert all(r["player_id"] != r["other_player_id"] for r in rows)


def test_entries_come_only_from_players_in_the_pool_with_their_percentiles():
    def row(player_id, stat, percentile, in_pool=True):
        return {
            "season": 2024,
            "player_id": player_id,
            "name": f"P{player_id}",
            "team": "TOR",
            "position": "C",
            "position_group": "F",
            "in_pool": in_pool,
            "stat": stat,
            "percentile": percentile,
        }

    entries = sm.build_entries([row(1, "a", 10), row(1, "b", None), row(1, "c", 30), row(2, "a", 90, in_pool=False)])
    assert [e["player_id"] for e in entries] == [1] and entries[0]["percentiles"] == {"a": 10, "c": 30}
