"""Tests for scripts/export_app_data.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import export_app_data as ex  # noqa: E402
import pytest  # noqa: E402


def make_sources(metrics, seasons, skip=()):
    for src, _ in ex.plan_copies(seasons, metrics, Path("unused")):
        if src.name in skip:
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(src.name.encode())


def test_plan_has_every_table_for_every_season_plus_similarity(tmp_path):
    pairs = ex.plan_copies([2024, 2025], tmp_path / "m", tmp_path / "a")
    assert len(pairs) == 2 * len(ex.SEASON_TABLES) + len(ex.ALL_SEASON_TABLES)
    assert (
        tmp_path / "m" / "season=2025" / "team_season_app.parquet",
        tmp_path / "a" / "season=2025" / "team_season_app.parquet",
    ) in pairs
    assert (tmp_path / "m" / "player_similarity.parquet", tmp_path / "a" / "player_similarity.parquet") in pairs


def test_export_copies_files_unchanged(tmp_path):
    metrics, app = tmp_path / "m", tmp_path / "a"
    make_sources(metrics, [2025])
    copied = ex.export([2025], metrics, app)
    assert len(copied) == len(ex.SEASON_TABLES) + 1
    assert (app / "season=2025" / "player_season_app.parquet").read_bytes() == b"player_season_app.parquet"
    assert (app / "player_similarity.parquet").read_bytes() == b"player_similarity.parquet"
    assert all(size > 0 for _, size in copied)


def test_missing_source_stops_the_export_and_writes_nothing(tmp_path):
    metrics, app = tmp_path / "m", tmp_path / "a"
    make_sources(metrics, [2025], skip=("team_season_app.parquet",))
    with pytest.raises(FileNotFoundError, match="team_season_app"):
        ex.export([2025], metrics, app)
    assert not app.exists()
