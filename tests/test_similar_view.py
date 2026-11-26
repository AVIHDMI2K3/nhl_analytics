"""Tests for app/similar_view.py."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
import similar_view as sv  # noqa: E402


def entry_row(season, player_id, mode, rank, other_id, similarity, other_season=None, other_team="TOR", **gaps):
    row = {
        "season": season,
        "player_id": player_id,
        "name": f"P{player_id}",
        "position_group": "F",
        "mode": mode,
        "rank": rank,
        "other_season": season if other_season is None else other_season,
        "other_player_id": other_id,
        "other_name": f"P{other_id}",
        "other_team": other_team,
        "other_position": "C",
        "similarity": similarity,
        "gap_scoring": 10.0,
        "gap_shot_share": 12.0,
        "gap_shot_volume": 14.0,
        "gap_physical": 16.0,
        "gap_usage": 2.0,
    }
    row.update(gaps)
    return row


@pytest.fixture
def similarity():
    return pd.DataFrame(
        [
            entry_row(2025, 1, "same_season", 2, 3, 80.0),
            entry_row(2025, 1, "same_season", 1, 2, 90.0),
            entry_row(2025, 1, "all_seasons", 1, 2, 90.0),
            entry_row(2025, 1, "all_seasons", 2, 3, 85.0, other_season=2023, other_team="TOT"),
            entry_row(2025, 2, "same_season", 1, 1, 90.0),
            entry_row(2023, 3, "same_season", 1, 4, 70.0),
        ]
    )


@pytest.fixture
def percentiles():
    rows = []
    players = ((1, "Ann", "TOR"), (2, "Bob", "VAN, MIN"), (3, "Cy", "CGY"), (9, "Low Minutes", "SEA"))
    for player_id, name, teams in players:
        rows.append(
            {
                "player_id": player_id,
                "name": name,
                "position": "C",
                "position_group": "F",
                "teams": teams,
                "minutes_5v5": 900.0,
                "in_pool": True,
            }
        )
    return pd.DataFrame(rows)


def test_mode_options_put_the_default_first_and_name_every_mode(similarity):
    assert list(sv.mode_options(similarity).items()) == [("same_season", "Same season"), ("all_seasons", "All seasons")]
    extra = pd.concat([similarity, similarity.assign(mode="last_3")])
    assert sv.mode_options(extra)["last_3"] == "Last 3"
    assert next(iter(sv.mode_options(extra))) == "same_season"


def test_player_options_list_only_players_with_entries_that_season(similarity, percentiles):
    options = sv.player_options(percentiles, similarity, 2025)
    assert list(options) == [1, 2]  # Cy has an entry only in 2023, Low Minutes none
    assert options[2] == "Bob (VAN, MIN, C)"


def test_matches_are_one_players_rows_in_one_mode_by_rank(similarity):
    found = sv.matches(similarity, 2025, 1, "same_season")
    assert list(found["rank"]) == [1, 2]
    assert list(found["other_player_id"]) == [2, 3]
    assert list(sv.matches(similarity, 2025, 1, "all_seasons")["other_season"]) == [2025, 2023]
    assert sv.matches(similarity, 2025, 99, "same_season").empty


def test_display_table_has_the_match_the_score_and_a_gap_per_category(similarity):
    found = sv.matches(similarity, 2025, 1, "all_seasons")
    table = sv.display_table(found, lambda season: f"S{season}")
    assert table.index.name == "Rank"
    assert list(table.columns) == [
        "Player",
        "Season",
        "Team",
        "Pos",
        "Similarity",
        "Scoring",
        "Shot share",
        "Shot volume",
        "Physical",
        "Usage",
    ]
    assert list(table["Player"]) == ["P2", "P3"]
    assert list(table["Season"]) == ["S2025", "S2023"]
    assert list(table["Team"]) == ["TOR", "TOT"]
    assert table.loc[1, "Similarity"] == 90.0
    assert table.loc[1, "Usage"] == 2.0


def rgb_of(css):
    return tuple(int(part) for part in re.search(r"color: rgb\((\d+), (\d+), (\d+)\)", css).groups())


def test_similarity_style_is_empty_without_a_score_and_bold_with_one():
    assert sv.similarity_style(float("nan")) == ""
    assert sv.similarity_style(None) == ""
    assert "font-weight: 700" in sv.similarity_style(75.0)


def test_similarity_style_uses_each_bands_own_colors_at_its_ends():
    red, amber, green = sv.BANDS
    assert rgb_of(sv.similarity_style(0)) == red[2]
    assert rgb_of(sv.similarity_style(30)) == red[3]  # 30 is still red
    assert rgb_of(sv.similarity_style(60)) == amber[3]  # 60 is still amber
    assert rgb_of(sv.similarity_style(100)) == green[3]


def test_similarity_style_changes_band_just_above_30_and_60():
    red, amber, green = sv.BANDS
    assert abs(rgb_of(sv.similarity_style(31))[0] - amber[2][0]) <= 2  # near the start of amber
    assert abs(rgb_of(sv.similarity_style(61))[1] - green[2][1]) <= 2  # near the start of green


def test_similarity_style_shades_inside_a_band_and_clips_outside_the_scale():
    low, high = rgb_of(sv.similarity_style(65)), rgb_of(sv.similarity_style(95))
    assert low != high
    assert rgb_of(sv.similarity_style(-5)) == rgb_of(sv.similarity_style(0))
    assert rgb_of(sv.similarity_style(120)) == rgb_of(sv.similarity_style(100))


def test_styled_shows_one_decimal_a_dash_for_a_missing_gap_and_the_color(similarity):
    table = sv.display_table(sv.matches(similarity, 2025, 1, "all_seasons"), lambda season: f"S{season}")
    html = sv.styled(table).to_html()
    assert "color: rgb(" in html
    assert sv.styled(table.assign(Scoring=float("nan"))).to_html().count(">-<") == len(table)


def test_chosen_match_is_the_clicked_row_with_its_own_season(similarity):
    found = sv.matches(similarity, 2025, 1, "all_seasons")
    assert sv.chosen_match(found, [1]) == {"season": 2023, "player_id": 3, "name": "P3"}


def test_chosen_match_is_none_without_a_click_or_with_a_stale_one(similarity):
    found = sv.matches(similarity, 2025, 1, "all_seasons")
    assert sv.chosen_match(found, []) is None
    assert sv.chosen_match(found, [len(found)]) is None
