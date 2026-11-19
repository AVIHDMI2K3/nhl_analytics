"""Phase 8: build the skater table the Players page shows, for one season.

Run from the repo root with the `nhl` conda environment active:

    python src/nhl_pipeline/transform/build_player_app.py --season 2025

Reads  data/metrics/season=2025/player_season_display.parquet, player_season_advanced.parquet,
       player_season_special_teams.parquet, player_season_faceoffs.parquet
Writes data/metrics/season=2025/player_season_app.parquet   one row per skater and kind

See player_app.py for the columns and the joins.
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from player_app import build_player_rows

REPO_ROOT = Path(__file__).resolve().parents[3]
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
SAMPLE_PLAYERS = ("Auston Matthews", "Connor McDavid", "Jack Hughes", "Cale Makar", "Luke Hughes", "Quinn Hughes")


def fmt(value, width, decimals=1):
    if value is None:
        return f"{'-':>{width}}"
    return f"{value:>{width},.{decimals}f}" if decimals else f"{value:>{width}}"


def main():
    parser = argparse.ArgumentParser(description="Build the Players page table for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    metrics = args.metrics_root / f"season={args.season}"
    read = lambda name: pq.read_table(metrics / f"{name}.parquet").to_pylist()  # noqa: E731
    rows = build_player_rows(read("player_season_display"), read("player_season_advanced"),
                             read("player_season_special_teams"), read("player_season_faceoffs"))
    out = metrics / "player_season_app.parquet"
    pq.write_table(pa.Table.from_pylist(rows), out, compression="zstd")

    print(f"season {args.season}: {len(rows)} rows, {len(rows[0])} columns -> {out}")
    for label, column in (("5v5", "minutes_5v5"), ("power play", "pp_minutes"), ("penalty kill", "pk_minutes"),
                          ("faceoffs", "fo_faceoffs")):
        missing = sum(1 for r in rows if r[column] is None)
        print(f"  rows with no {label} row: {missing}")

    print(f"\n  {'player':<18} {'kind':<5} {'GP':>3} {'G':>3} {'A':>3} {'PTS':>4} {'5v5 min':>8} {'CF%':>5} "
          f"{'RelCF%':>6} {'PP min':>7} {'PK min':>7} {'FO':>5} {'FO%':>5}")
    for r in rows:
        if r["name"] in SAMPLE_PLAYERS:
            print(f"  {r['name']:<18} {r['kind']:<5} {r['games_played']:>3} {r['goals']:>3} {r['assists']:>3} "
                  f"{r['points']:>4} {fmt(r['minutes_5v5'], 8)} {fmt(r['cf_pct_5v5'], 5)} "
                  f"{fmt(r['cf_pct_rel_5v5'], 6)} {fmt(r['pp_minutes'], 7)} {fmt(r['pk_minutes'], 7)} "
                  f"{fmt(r['fo_faceoffs'], 5, 0)} {fmt(r['fo_pct'], 5)}")


if __name__ == "__main__":
    main()