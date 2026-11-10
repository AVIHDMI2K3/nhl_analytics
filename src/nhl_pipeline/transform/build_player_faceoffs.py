"""Phase 4.12: build the skater faceoff table for one season.

Run from the repo root with the `nhl` conda environment active, after build_season_totals.py:

    python src/nhl_pipeline/transform/build_player_faceoffs.py --season 2025

Reads  data/staging/season=2025/{events,games,players}.parquet, data/metrics/season=2025/player_season_totals.parquet
Writes data/metrics/season=2025/player_season_faceoffs.parquet

One row per skater, team (or combined row for a traded player) and situation (all, ev, pp, sh, oz, dz, nz); see
faceoffs.py. games_included is the number of games in which the skater took a faceoff in the situation's
team row. Counted from the events, so every game is included. Checked with scripts/check_player_faceoffs.py.
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from advanced_stats import build_advanced_display
from build_season_display import full_names, team_abbrevs
from faceoffs import COUNT_COLUMNS, RATE_COLUMNS, SITUATIONS, add_faceoff_rates, count_faceoffs

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
EVENT_COLUMNS = [
    "game_id", "event_type", "event_owner_team_id", "zone_code", "situation_code", "winning_player_id", "losing_player_id",
]
SCHEMA = pa.schema(
    [("season", pa.int64()), ("player_id", pa.int64()), ("name", pa.string()), ("position", pa.string()),
     ("kind", pa.string()), ("team_id", pa.int64()), ("team", pa.string()), ("teams", pa.string()),
     ("situation", pa.string()), ("games_played", pa.int64()), ("games_included", pa.int64())]
    + [(column, pa.int64()) for column in COUNT_COLUMNS]
    + [(column, pa.float64()) for column in RATE_COLUMNS]
)


def write_table(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, compression="zstd")


def main():
    parser = argparse.ArgumentParser(description="Build the skater faceoff table.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    metrics = args.metrics_root / f"season={args.season}"
    staging = args.staging_root / f"season={args.season}"
    games = {g["game_id"]: g for g in pq.read_table(
        staging / "games.parquet", columns=["game_id", "home_team_id", "away_team_id"]).to_pylist()}
    events = pq.read_table(staging / "events.parquet", columns=EVENT_COLUMNS).to_pylist()
    season_rows = pq.read_table(metrics / "player_season_totals.parquet").to_pylist()

    totals, played, skipped = count_faceoffs(events, games)
    rows = build_advanced_display(
        totals, played, season_rows, full_names(staging), team_abbrevs(staging),
        situations=SITUATIONS, columns=COUNT_COLUMNS, add_rates_to=add_faceoff_rates,
    )
    for row in rows:
        row["season"] = args.season
    out = metrics / "player_season_faceoffs.parquet"
    write_table(out, rows)

    in_table = {(r["player_id"], r["team_id"]) for r in season_rows}
    lost = sum(c["faceoffs"] for (p, t, s), c in totals.items() if s == "all" and (p, t) not in in_table)
    print(f"Season {args.season}: {len(rows)} rows ({len({r['player_id'] for r in rows})} skaters)")
    print(f"Written to {out}")
    print(f"Faceoff events skipped (missing player, team or game): {skipped}; faceoffs of players not in the season totals: {lost}")
    shown = [r for r in rows if r["situation"] == "all" and (r["kind"] != "team" or r["teams"] == r["team"])]
    top = sorted((r for r in shown if r["faceoffs"] >= 500), key=lambda r: -r["faceoff_pct"])
    print("\nFaceoff %, best five and worst five (at least 500 faceoffs):")
    for r in top[:5] + top[-5:]:
        print(f"  {r['name']:24s} {r['team']:4s} {r['faceoff_wins']:4d}/{r['faceoffs']:4d}  {r['faceoff_pct']:.1f}%")


if __name__ == "__main__":
    main()