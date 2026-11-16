"""Phase 6: build the fan-facing line and defense-pair table for one season.

Run from the repo root with the `nhl` conda environment active, after build_line_tables.py, build_unit_zone_starts.py and build_season_display.py:

    python src/nhl_pipeline/transform/build_line_display.py --season 2025
    python src/nhl_pipeline/transform/build_line_display.py --season 2025 --min-minutes 100

Reads  data/metrics/season=2025/unit_season_5v5.parquet, unit_zone_starts_5v5.parquet, player_season_display.parquet
       data/staging/season=2025/{players,games}.parquet
Writes data/metrics/season=2025/unit_season_display.parquet   one row per unit with at least --min-minutes together

See line_display.py for the id, label and position rules. A player traded during the season is looked up for the team
of the unit (his 'team' rows of player_season_display), so a unit is labelled with the position he had for that team.
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from build_season_display import full_names, team_abbrevs, write_table
from line_display import MAX_MEMBERS, build_unit_display

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
DEFAULT_MIN_MINUTES = 60
RATE_NAMES = ("cf_pct", "ff_pct", "sf_pct", "gf_pct", "sh_pct", "sv_pct", "pdo", "cf_per_60", "ca_per_60",
              "gf_per_60", "ga_per_60")
SCHEMA = pa.schema(
    [("season", pa.int64()), ("unit_id", pa.string()), ("team_id", pa.int64()), ("team", pa.string()),
     ("unit_type", pa.string()), ("label", pa.string()), ("positions", pa.string()), ("player_names", pa.string())]
    + [(f"player_{i + 1}_id", pa.int64()) for i in range(MAX_MEMBERS)]
    + [("games", pa.int64()), ("minutes", pa.float64()), ("minutes_per_game", pa.float64())]
    + [("oz_starts", pa.int64()), ("dz_starts", pa.int64()), ("nz_starts", pa.int64()), ("oz_start_pct", pa.float64())]
    + [(name, pa.int64()) for name in ("cf", "ca", "ff", "fa", "sf", "sa", "gf", "ga")]
    + [(name, pa.float64()) for name in RATE_NAMES]
)


def main():
    parser = argparse.ArgumentParser(description="Build the fan-facing line and pair table for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--min-minutes", type=float, default=DEFAULT_MIN_MINUTES)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    staging = args.staging_root / f"season={args.season}"
    metrics = args.metrics_root / f"season={args.season}"
    names, abbrevs = full_names(staging), team_abbrevs(staging)
    info = {}
    for row in pq.read_table(metrics / "player_season_display.parquet").to_pylist():
        if row["kind"] == "team":
            info[(row["player_id"], row["team_id"])] = (names.get(row["player_id"]) or row["name"], row["position"])
    season_rows = pq.read_table(metrics / "unit_season_5v5.parquet").to_pylist()
    zone_starts = {(z["team_id"], z["unit_type"], tuple(sorted(z["player_ids"]))): z for z in pq.read_table(
        metrics / "unit_zone_starts_5v5.parquet").to_pylist()}
    rows = build_unit_display(season_rows, info, abbrevs, min_seconds=int(args.min_minutes * 60),
                              zone_starts=zone_starts)
    for row in rows:
        row["season"] = args.season
    write_table(metrics / "unit_season_display.parquet", rows, SCHEMA)

    print(f"season {args.season}: {len(rows)} units with at least {args.min_minutes:g} minutes "
          f"(of {len(season_rows)}) -> {metrics / 'unit_season_display.parquet'}")
    unknown = sum(1 for r in rows if "?" in r["positions"])
    print(f"units with a player whose position is unknown: {unknown}")
    for team in ("TOR", "BOS", "EDM"):
        for unit_type in ("line", "pair"):
            top = [r for r in rows if r["team"] == team and r["unit_type"] == unit_type][:3]
            for r in top:
                print(f"  {team} {unit_type:4} {r['label']:<42} {r['positions']:<6} {r['minutes']:>6.1f} min "
                      f"{r['games']:>3} gp  CF% {r['cf_pct']:.1f}  GF% {r['gf_pct']}  "
                      f"OZ start% {r['oz_start_pct']}")


if __name__ == "__main__":
    main()