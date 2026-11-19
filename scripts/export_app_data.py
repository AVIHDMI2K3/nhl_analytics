"""Phase 8: copy the tables the Streamlit app reads into a small committed folder, app_data/.

Run from the repo root with the `nhl` conda environment active, after the metrics tables are built:

    python scripts/export_app_data.py
    python scripts/export_app_data.py --seasons 2024 2025

Reads  data/metrics/season=YYYY/<table>.parquet   (gitignored)
Writes app_data/season=YYYY/<table>.parquet       (committed, so Streamlit Community Cloud can read it)
       app_data/player_similarity.parquet         (one file covering all seasons)

Nothing is changed on the way: files are copied as they are. A missing source table stops the export, so a
half-empty app_data/ is never produced. Prints every file with its size and the total.
"""

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
APP_DATA_ROOT = REPO_ROOT / "app_data"
DEFAULT_SEASONS = (2023, 2024, 2025)
SEASON_TABLES = (
    "player_season_app",
    "goalie_season_display",
    "unit_season_display",
    "player_season_percentiles",
    "team_season_app",
)
ALL_SEASON_TABLES = ("player_similarity",)


def plan_copies(seasons, metrics_root=METRICS_ROOT, app_data_root=APP_DATA_ROOT):
    """List of (source, destination) pairs for the given seasons."""
    pairs = []
    for season in seasons:
        for table in SEASON_TABLES:
            pairs.append((metrics_root / f"season={season}" / f"{table}.parquet",
                          app_data_root / f"season={season}" / f"{table}.parquet"))
    for table in ALL_SEASON_TABLES:
        pairs.append((metrics_root / f"{table}.parquet", app_data_root / f"{table}.parquet"))
    return pairs


def export(seasons, metrics_root=METRICS_ROOT, app_data_root=APP_DATA_ROOT):
    """Copy every table. Returns [(destination, size in bytes)]. Raises FileNotFoundError listing missing sources."""
    pairs = plan_copies(seasons, metrics_root, app_data_root)
    missing = [str(src) for src, _ in pairs if not src.is_file()]
    if missing:
        raise FileNotFoundError("missing source tables:\n  " + "\n  ".join(missing))
    copied = []
    for src, dst in pairs:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        copied.append((dst, dst.stat().st_size))
    return copied


def main():
    parser = argparse.ArgumentParser(description="Copy the app's tables into app_data/.")
    parser.add_argument("--seasons", type=int, nargs="+", default=list(DEFAULT_SEASONS))
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    parser.add_argument("--app-data-root", type=Path, default=APP_DATA_ROOT)
    args = parser.parse_args()

    try:
        copied = export(args.seasons, args.metrics_root, args.app_data_root)
    except FileNotFoundError as error:
        print(error)
        sys.exit(1)
    for dst, size in copied:
        print(f"  {dst.relative_to(args.app_data_root).as_posix():<60} {size / 1024:>9,.1f} KB")
    total = sum(size for _, size in copied)
    print(f"\n{len(copied)} files, {total / 1024 / 1024:.2f} MB in total -> {args.app_data_root}")


if __name__ == "__main__":
    main()