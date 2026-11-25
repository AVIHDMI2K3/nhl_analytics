"""Tests for app/compare_chart.py. Skipped when Altair is not installed (it comes with Streamlit)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

pytest.importorskip("altair")

import compare_chart as cc  # noqa: E402
import compare_view as cv  # noqa: E402
import pandas as pd  # noqa: E402

LABELS = {
    "goals_per_60": "Goals per 60",
    "ca_per_60": "Shot attempts against per 60 (5v5, fewer is better)",
    "toi_per_game": "Time on ice per game (minutes)",
}
FIRST, SECOND = "Ann (2025-26)", "Bob (2025-26)"


def comparison(missing=False):
    rows = []
    for player_id, percentiles in ((1, (80.0, 90.0, 70.0)), (2, (99.0, 70.0, 85.0))):
        for (stat, label), percentile in zip(LABELS.items(), percentiles, strict=True):
            rows.append(
                {
                    "player_id": player_id,
                    "stat": stat,
                    "label": label,
                    "value": 1.5,
                    "percentile": percentile,
                    "in_pool": True,
                }
            )
    table = pd.DataFrame(rows)
    if missing:
        table.loc[(table["player_id"] == 1) & (table["stat"] == "goals_per_60"), "percentile"] = float("nan")
    return cv.comparison(table, 1, FIRST, table, 2, SECOND)


@pytest.mark.parametrize(
    ("label", "shown"),
    [
        ("Shot attempts against per 60 (5v5, fewer is better)", "Shot attempts against per 60"),
        ("Corsi % (5v5)", "Corsi %"),
        ("Giveaways per 60 (fewer is better)", "Giveaways per 60"),
        ("Time on ice per game (minutes)", "Time on ice per game (minutes)"),
        ("Assists per 60", "Assists per 60"),
    ],
)
def test_chart_label_drops_the_notes_the_chart_already_says(label, shown):
    assert cc.chart_label(label) == shown


def test_chart_has_one_small_chart_per_group():
    spec = cc.paired_dots(comparison(), FIRST, SECOND, "forwards").to_dict()
    assert len(spec["vconcat"]) == 3  # Scoring, Shot attempts (5v5), Ice time


def test_chart_names_both_players_and_the_pool():
    text = json.dumps(cc.paired_dots(comparison(), FIRST, SECOND, "forwards").to_dict())
    assert FIRST in text
    assert SECOND in text
    assert "Percentile among forwards" in text


def test_chart_builds_when_a_player_has_no_percentile_for_a_stat():
    spec = cc.paired_dots(comparison(missing=True), FIRST, SECOND, "defensemen").to_dict()
    assert len(spec["vconcat"]) == 3
