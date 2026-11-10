"""Check our skater faceoff table against the NHL's skater faceoff report.

Run from the repo root with the `nhl` conda environment active, after build_player_faceoffs.py and
ingest_reference.py:

    python scripts/check_player_faceoffs.py --season 2025

The report gives, per skater, the number of faceoffs (total, by strength and by zone) and the win percentage
for each. It compares our faceoff counts and win percentages for every skater (our team rows added up, so a
traded player is one skater). Percentages must agree to 0.1 point. Prints how many skaters agree exactly and
the largest difference, for each of the seven situations.
"""

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

RAW_ROOT = REPO_ROOT / "data" / "raw"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
# our situation -> (NHL count field, NHL percentage field)
FIELDS = {
    "all": ("totalFaceoffs", "faceoffWinPct"),
    "ev": ("evFaceoffs", "evFaceoffPct"),
    "pp": ("ppFaceoffs", "ppFaceoffPct"),
    "sh": ("shFaceoffs", "shFaceoffPct"),
    "oz": ("offensiveZoneFaceoffs", "offensiveZoneFaceoffPct"),
    "dz": ("defensiveZoneFaceoffs", "defensiveZoneFaceoffPct"),
    "nz": ("neutralZoneFaceoffs", "neutralZoneFaceoffPct"),
}
TOLERANCE_POINTS = 0.1


def percent_scale(values):
    """100 if the percentages are fractions (none above 1), else 1."""
    present = [v for v in values if v is not None]
    return 100 if present and max(present) <= 1.0 else 1


def our_totals(rows):
    """{(player_id, situation): (faceoffs, wins)} adding up each skater's team rows."""
    totals = defaultdict(lambda: [0, 0])
    for row in rows:
        if row["kind"] != "team":
            continue
        total = totals[(row["player_id"], row["situation"])]
        total[0] += row["faceoffs"]
        total[1] += row["faceoff_wins"]
    return totals


def compare(totals, report, situation):
    """(skaters, exact counts, ours total, NHL total, worst count difference, skaters with a percentage in both,
    percentages within tolerance, worst percentage difference in points)."""
    count_field, pct_field = FIELDS[situation]
    scale = percent_scale([r[pct_field] for r in report])
    exact = ours_sum = nhl_sum = worst = 0
    both = within = 0
    worst_pct = 0.0
    for row in report:
        faceoffs, wins = totals.get((row["playerId"], situation), (0, 0))
        nhl = row[count_field] or 0
        ours_sum += faceoffs
        nhl_sum += nhl
        exact += faceoffs == nhl
        if abs(faceoffs - nhl) > abs(worst):
            worst = faceoffs - nhl
        if row[pct_field] is not None and faceoffs:
            both += 1
            difference = 100 * wins / faceoffs - row[pct_field] * scale
            within += abs(difference) <= TOLERANCE_POINTS
            if abs(difference) > abs(worst_pct):
                worst_pct = difference
    return len(report), exact, ours_sum, nhl_sum, worst, both, within, worst_pct


def main():
    parser = argparse.ArgumentParser(description="Check the skater faceoff table against the NHL's report.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    rows = pq.read_table(METRICS_ROOT / f"season={args.season}" / "player_season_faceoffs.parquet").to_pylist()
    with gzip.open(RAW_ROOT / f"season={args.season}" / "reference" / "skater_faceoffs.json.gz", "rb") as handle:
        report = json.loads(handle.read())["data"]
    totals = our_totals(rows)
    print(f"Season {args.season}: {len(report)} skaters in the NHL's faceoff report")
    for situation, (count_field, _) in FIELDS.items():
        n, exact, mine, theirs, worst, both, within, worst_pct = compare(totals, report, situation)
        print(f"  {situation:3s} {count_field:24s} exact {exact:3d}/{n}  ours {mine} NHL {theirs}  worst {worst:+d} | "
              f"win % within {TOLERANCE_POINTS} point for {within}/{both}, worst {worst_pct:+.2f}")


if __name__ == "__main__":
    main()