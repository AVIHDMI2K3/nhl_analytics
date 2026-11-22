"""Phase 8: build the team table the Teams page shows, for one season.

Run from the repo root with the `nhl` conda environment active:

    python src/nhl_pipeline/transform/build_team_app.py --season 2025

Reads  data/metrics/season=2025/team_season_basic.parquet, team_season_advanced.parquet,
       team_season_special_teams.parquet
Writes data/metrics/season=2025/team_season_app.parquet   one row per team

See team_app.py for the columns and the rounding.
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from team_app import build_team_rows

REPO_ROOT = Path(__file__).resolve().parents[3]
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
SAMPLE_TEAMS = ("COL", "BOS", "EDM", "NJD", "TOR", "VAN")


def main():
    parser = argparse.ArgumentParser(description="Build the Teams page table for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    metrics = args.metrics_root / f"season={args.season}"
    basic = pq.read_table(metrics / "team_season_basic.parquet").to_pylist()
    advanced = pq.read_table(metrics / "team_season_advanced.parquet").to_pylist()
    special = pq.read_table(metrics / "team_season_special_teams.parquet").to_pylist()
    rows = build_team_rows(basic, advanced, special)
    out = metrics / "team_season_app.parquet"
    pq.write_table(pa.Table.from_pylist(rows), out, compression="zstd")

    missing_5v5 = [r["team"] for r in rows if r["cf_pct_5v5"] is None]
    missing_special = [r["team"] for r in rows if r["pp_pct"] is None]
    print(f"season {args.season}: {len(rows)} teams, {len(rows[0])} columns -> {out}")
    print(f"  teams with no 5v5 row: {missing_5v5 or 'none'}; with no special-teams row: {missing_special or 'none'}")
    print(
        f"\n  {'team':<4} {'GP':>3} {'PTS':>4} {'P%':>6} {'RW':>3} {'ROW':>4} {'DIFF':>5} {'CF%':>5} {'GF%':>5} "
        f"{'PP%':>5} {'PK%':>5}"
    )
    for r in rows:
        if r["team"] in SAMPLE_TEAMS:
            print(
                f"  {r['team']:<4} {r['games_played']:>3} {r['points']:>4} {r['points_pct']:>6.3f} "
                f"{r['regulation_wins']:>3} {r['row']:>4} {r['goal_diff']:>5} {r['cf_pct_5v5']:>5.1f} "
                f"{r['gf_pct_5v5']:>5.1f} {r['pp_pct']:>5.1f} {r['pk_pct']:>5.1f}"
            )


if __name__ == "__main__":
    main()
