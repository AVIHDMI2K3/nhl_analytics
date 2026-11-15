"""Why are a skater's Corsi and Fenwick not exact against Natural Stat Trick? (Phase 5)

Run from the repo root with the `nhl` conda environment active, with the NST all-situations skater file in place
(see check_against_nst.py):

    python scripts/diagnose_skater_gap.py --season 2023 --folder data/reference/nst

Our tables decide who was on the ice for an attempt from the shifts. At a line change the shifts can show an extra
or a missing skater, and then the NHL situation code (which counts the skaters) disagrees with our list: the
shot_attempts table marks these attempts with matches_situation = false. For every skater this counts the attempts
(Corsi for and against) he is listed on the ice for where the code and our list disagree, and compares that with
how far his Corsi (CF + CA) is from NST's. If the gaps come from these moments, skaters with none of them should
match NST almost exactly and the gap should grow with the count.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

from check_against_nst import match_skaters, number, read_nst  # noqa: E402

METRICS_ROOT = REPO_ROOT / "data" / "metrics"
BUCKETS = ((0, 0, "none"), (1, 2, "1-2"), (3, 5, "3-5"), (6, 10, "6-10"), (11, 10 ** 9, "11 or more"))
ATTEMPT_TYPES = ("goal", "shot-on-goal", "missed-shot", "blocked-shot")


def mismatched_attempts_by_player(attempts):
    """{player_id: attempts (for or against) he is listed on the ice for where matches_situation is false}."""
    counts = Counter()
    for attempt in attempts:
        if attempt["attempt_type"] not in ATTEMPT_TYPES or attempt["matches_situation"] is not False:
            continue
        for player in list(attempt["skater_ids_for"] or []) + list(attempt["skater_ids_against"] or []):
            counts[player] += 1
    return counts


def bucket_of(count):
    for low, high, label in BUCKETS:
        if low <= count <= high:
            return label
    return BUCKETS[-1][2]


def summarize(rows):
    """{bucket: (skaters, exact, within 2, mean absolute gap)} from [(mismatched attempts, gap)]."""
    grouped = {label: [] for _, _, label in BUCKETS}
    for count, gap in rows:
        grouped[bucket_of(count)].append(abs(gap))
    return {label: (len(gaps), sum(1 for g in gaps if g == 0), sum(1 for g in gaps if g <= 2),
                    sum(gaps) / len(gaps) if gaps else None) for label, gaps in grouped.items()}


def main():
    parser = argparse.ArgumentParser(description="Relate skater Corsi gaps to line-change mismatches.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--folder", type=Path, required=True)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    metrics = METRICS_ROOT / f"season={args.season}"
    attempts = pq.read_table(metrics / "shot_attempts.parquet", columns=[
        "attempt_type", "matches_situation", "skater_ids_for", "skater_ids_against"]).to_pylist()
    mismatches = mismatched_attempts_by_player(attempts)
    total_attempts = sum(1 for a in attempts if a["attempt_type"] in ATTEMPT_TYPES)
    flagged = sum(1 for a in attempts if a["attempt_type"] in ATTEMPT_TYPES and a["matches_situation"] is False)
    print(f"Season {args.season}: {flagged} of {total_attempts} attempts ({100 * flagged / total_attempts:.2f}%) have an on-ice list "
          f"that disagrees with the situation code")

    players = pq.read_table(metrics / "player_season_advanced.parquet").to_pylist()
    ours = [r for r in players if r["situation"] == "all" and (r["kind"] == "total" or r["teams"] == r["team"])]
    nst_rows = read_nst(args.folder / f"nst_skaters_all_{args.season}.csv")
    matched, _, _ = match_skaters(nst_rows, ours)

    rows = []
    for index, mine in matched.items():
        nst = nst_rows[index]
        gap = (mine["cf"] + mine["ca"]) - (number(nst["CF"]) + number(nst["CA"]))
        rows.append((mismatches.get(mine["player_id"], 0), gap))
    print("\nSkaters by the number of disagreeing attempts they are on the ice for, and how far CF + CA is from NST's:")
    print(f"  {'disagreeing attempts':22s} {'skaters':>8s} {'exact':>7s} {'within 2':>9s} {'mean |gap|':>11s}")
    for label, (n, exact, near, mean) in summarize(rows).items():
        print(f"  {label:22s} {n:8d} {exact:7d} {near:9d} {'' if mean is None else format(mean, '11.1f')}")
    biggest = sorted(rows, key=lambda r: -abs(r[1]))[:10]
    print("\nTen largest gaps (disagreeing attempts, gap): " + "; ".join(f"({c}, {g:+.0f})" for c, g in biggest))


if __name__ == "__main__":
    main()