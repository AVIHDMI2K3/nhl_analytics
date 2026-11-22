"""Phase 7: build the player similarity table (all seasons together).

Run from the repo root with the `nhl` conda environment active, after build_player_percentiles.py for each season:

    python src/nhl_pipeline/transform/build_player_similarity.py
    python src/nhl_pipeline/transform/build_player_similarity.py --top-n 20

Reads  data/metrics/season=*/player_season_percentiles.parquet
Writes data/metrics/player_similarity.parquet   for each skater-season in the pool, his closest skater-seasons

mode = same_season: the closest players of the same season; all_seasons: the closest player-seasons of any season.
A player's own other seasons are never matches, so every match is a different player. Forwards are only matched with
forwards and defensemen with defensemen. similarity is 100 minus the average gap in percentile points, with
every category of
stats weighted equally; the gap_* columns show the gap per category. See similarity.py.
"""

import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from similarity import CATEGORIES, build_entries, nearest

REPO_ROOT = Path(__file__).resolve().parents[3]
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
DEFAULT_TOP_N = 15
SCHEMA = pa.schema(
    [
        ("season", pa.int64()),
        ("player_id", pa.int64()),
        ("name", pa.string()),
        ("position_group", pa.string()),
        ("mode", pa.string()),
        ("rank", pa.int64()),
        ("other_season", pa.int64()),
        ("other_player_id", pa.int64()),
        ("other_name", pa.string()),
        ("other_team", pa.string()),
        ("other_position", pa.string()),
        ("similarity", pa.float64()),
    ]
    + [(f"gap_{category}", pa.float64()) for category in CATEGORIES]
)
SHORT = {"scoring": "scoring", "shot_share": "share", "shot_volume": "volume", "physical": "physical", "usage": "usage"}
SAMPLES = (("McDavid", 2024), ("Makar", 2024), ("Matthews", 2023), ("Quinn Hughes", 2024))


def main():
    parser = argparse.ArgumentParser(description="Build the player similarity table.")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    files = sorted(args.metrics_root.glob("season=*/player_season_percentiles.parquet"))
    if not files:
        raise SystemExit("no player_season_percentiles.parquet found; run build_player_percentiles.py first")
    percentile_rows = []
    for file in files:
        percentile_rows.extend(pq.read_table(file).to_pylist())
    entries = build_entries(percentile_rows)
    rows = nearest(entries, top_n=args.top_n)
    out = args.metrics_root / "player_similarity.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), out, compression="zstd")

    print(f"{len(files)} seasons, {len(entries)} skater-seasons in the pool, {len(rows)} rows -> {out}")
    for group in ("F", "D"):
        print(f"  {group}: {sum(1 for e in entries if e['group'] == group)} skater-seasons")

    for name, season in SAMPLES:
        for entry in (e for e in entries if name in e["name"] and e["season"] == season):
            for mode in ("same_season", "all_seasons"):
                mine = [r for r in rows if (r["season"], r["player_id"]) == entry["key"] and r["mode"] == mode][:5]
                print(f"\n  {entry['name']} {season} ({entry['team']}) - closest, {mode.replace('_', ' ')}")
                for r in mine:
                    gaps = " ".join(f"{SHORT[c]} {r[f'gap_{c}']:.0f}" for c in CATEGORIES if r[f"gap_{c}"] is not None)
                    print(
                        f"    {r['rank']}. {r['other_name']:<22} {r['other_season']} {r['other_team']:<4} "
                        f"{r['similarity']:.1f}   gaps: {gaps}"
                    )


if __name__ == "__main__":
    main()
