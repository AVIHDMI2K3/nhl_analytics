"""Phase 4.6: build the fan-facing skater and goalie season tables for one season.

Run from the repo root with the `nhl` conda environment active, after build_season_totals.py:

    python src/nhl_pipeline/transform/build_season_display.py --season 2025

Reads  data/metrics/season=2025/{player,goalie}_season_totals.parquet
       data/staging/season=2025/{games,players}.parquet
Writes data/metrics/season=2025/player_season_display.parquet      (skaters)
       data/metrics/season=2025/goalie_season_display.parquet      (goalies)

See season_display.py for what a row holds.
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from season_display import GOALIE_RATE_COLUMNS, RATE_COLUMNS, build_goalie_display, build_season_display
from season_totals import GOALIE_COLUMNS, SUM_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
IDENTITY_FIELDS = [
    ("season", pa.int64()), ("player_id", pa.int64()), ("name", pa.string()), ("position", pa.string()),
    ("kind", pa.string()), ("team_id", pa.int64()), ("team", pa.string()), ("teams", pa.string()),
    ("games_played", pa.int64()),
]
SCHEMA = pa.schema(
    IDENTITY_FIELDS
    + [(column, pa.int64()) for column in SUM_COLUMNS]
    + [(column, pa.float64()) for column in RATE_COLUMNS]
)
GOALIE_SCHEMA = pa.schema(
    IDENTITY_FIELDS
    + [(column, pa.int64()) for column in GOALIE_COLUMNS]
    + [(column, pa.float64()) for column in GOALIE_RATE_COLUMNS]
)


def write_table(path, rows, schema=SCHEMA):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")


def full_names(staging):
    """player id -> 'First Last', from the game rosters (a later game overwrites an earlier one)."""
    names = {}
    rows = pq.read_table(staging / "players.parquet", columns=["game_id", "player_id", "first_name", "last_name"])
    for row in sorted(rows.to_pylist(), key=lambda r: r["game_id"]):
        full = " ".join(part for part in (row["first_name"], row["last_name"]) if part)
        if full:
            names[row["player_id"]] = full
    return names


def team_abbrevs(staging):
    abbrevs = {}
    for game in pq.read_table(
        staging / "games.parquet", columns=["home_team_id", "home_team", "away_team_id", "away_team"]
    ).to_pylist():
        abbrevs[game["home_team_id"]] = game["home_team"]
        abbrevs[game["away_team_id"]] = game["away_team"]
    return abbrevs


def main():
    parser = argparse.ArgumentParser(description="Build the fan-facing skater and goalie season tables.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    metrics = args.metrics_root / f"season={args.season}"
    staging = args.staging_root / f"season={args.season}"
    totals = pq.read_table(metrics / "player_season_totals.parquet").to_pylist()
    rows = build_season_display(totals, full_names(staging), team_abbrevs(staging))
    for row in rows:
        row["season"] = args.season
    out = metrics / "player_season_display.parquet"
    write_table(out, rows)

    kinds = {k: sum(1 for r in rows if r["kind"] == k) for k in ("total", "team")}
    print(f"Season {args.season}: {len(rows)} rows ({kinds['team']} team rows, {kinds['total']} combined rows for traded players)")
    print(f"Written to {out}")
    shown = [r for r in rows if r["kind"] != "team" or r["teams"] == r["team"]]
    print("\nTop 10 by points (one line per player, traded players combined):")
    for r in sorted(shown, key=lambda r: (-r["points"], -r["goals"]))[:10]:
        print(f"  {r['name']:24s} {r['team']:4s} {r['position']:2s} GP {r['games_played']:3d}  G {r['goals']:3d}  "
              f"A {r['assists']:3d}  P {r['points']:3d}  +/- {r['plus_minus']:+4d}  P/60 {r['points_per_60']:.2f}")
    traded = [r for r in rows if r["kind"] == "total"][:3]
    if traded:
        print("\nA few traded players (combined line first, then each team):")
        for total in traded:
            for r in [x for x in rows if x["player_id"] == total["player_id"]]:
                print(f"  {r['name']:24s} {r['team']:4s} GP {r['games_played']:3d}  G {r['goals']:3d}  P {r['points']:3d}")

    goalie_totals = pq.read_table(metrics / "goalie_season_totals.parquet").to_pylist()
    goalie_rows = build_goalie_display(goalie_totals, full_names(staging), team_abbrevs(staging))
    for row in goalie_rows:
        row["season"] = args.season
    goalie_out = metrics / "goalie_season_display.parquet"
    write_table(goalie_out, goalie_rows, GOALIE_SCHEMA)
    print(f"\nGoalies: {len(goalie_rows)} rows, written to {goalie_out}")
    print("Top 10 by games started (one line per goalie, traded goalies combined):")
    shown_goalies = [r for r in goalie_rows if r["kind"] != "team" or r["teams"] == r["team"]]
    for r in sorted(shown_goalies, key=lambda r: -r["games_started"])[:10]:
        print(f"  {r['name']:24s} {r['team']:4s} GP {r['games_played']:3d}  GS {r['games_started']:3d}  "
              f"W {r['wins']:2d}  L {r['losses']:2d}  OTL {r['ot_losses']:2d}  SV% {r['save_pct']:.2f}  "
              f"GAA {r['goals_against_avg']:.2f}  SO {r['shutouts']:2d}")


if __name__ == "__main__":
    main()