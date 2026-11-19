"""Tests for src/nhl_pipeline/transform/column_labels.py."""

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))

import pytest  # noqa: E402

import column_labels as cl  # noqa: E402

APP_DATA = ROOT / "app_data" / "season=2025"
TABLE_FILES = {"players": "player_season_app", "teams": "team_season_app", "goalies": "goalie_season_display",
               "lines": "unit_season_display"}
TABLES = tuple(TABLE_FILES)


@pytest.mark.parametrize("table", TABLES)
def test_every_shown_column_has_a_label_and_a_description(table):
    shown = list(cl.FIXED[table]) + [c for _, cols in cl.GROUPS[table] for c in cols]
    for column in shown:
        assert cl.label(column).strip(), column
        assert cl.description(table, column).strip(), column


@pytest.mark.parametrize("table", TABLES)
def test_no_column_is_listed_twice(table):
    counts = Counter(cl.all_columns(table))
    assert [c for c, n in counts.items() if n > 1] == []


@pytest.mark.parametrize("table", TABLES)
def test_labels_are_unique_within_a_group(table):
    for group, cols in cl.GROUPS[table]:
        labels = [cl.label(c) for c in cols]
        assert len(labels) == len(set(labels)), group


@pytest.mark.parametrize("table", TABLES)
def test_defaults_are_grouped_columns(table):
    grouped = {c for _, cols in cl.GROUPS[table] for c in cols}
    assert set(cl.DEFAULTS[table]) <= grouped
    assert len(cl.DEFAULTS[table]) == len(set(cl.DEFAULTS[table]))


def test_nothing_in_the_label_tables_is_unused():
    used = {c for t in TABLES for c in cl.all_columns(t)}
    assert set(cl.LABELS) - used == set()
    assert set(cl.DESCRIPTIONS) - used == set()
    for table, overrides in cl.OVERRIDES.items():
        assert set(overrides) <= set(cl.all_columns(table))


def test_visible_groups_follows_the_selection():
    shown = cl.visible_groups("teams", ["points", "pp_pct"])
    assert shown == [("Standings", ["points"]), ("Power play", ["pp_pct"])]
    assert cl.visible_groups("teams")[0][0] == "Standings"


def test_override_replaces_the_shared_description():
    assert "Standings points" in cl.description("teams", "points")
    assert cl.description("players", "points") == "Goals plus assists."


@pytest.mark.parametrize("table", TABLES)
def test_columns_match_the_app_data_files(table):
    path = APP_DATA / f"{TABLE_FILES[table]}.parquet"
    if not path.is_file():
        pytest.skip("app_data/ not exported yet")
    import pyarrow.parquet as pq
    in_file = set(pq.read_table(path).schema.names)
    listed = set(cl.all_columns(table))
    assert in_file - listed == set(), f"columns in {path.name} with no label entry"
    assert listed - in_file == set(), f"labeled columns missing from {path.name}"