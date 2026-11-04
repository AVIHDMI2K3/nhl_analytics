"""Check the advanced on-ice skater table (Phase 4.7).

Run from the repo root with the `nhl` conda environment active, after build_player_advanced.py:

    python scripts/check_player_advanced.py --season 2025

A. Time on ice by strength per skater against the NHL's skater time-on-ice report.
B. Exact identities that must hold if the sums are right:
   1. at 5v5 every attempt for one team is an attempt against the other with five skaters on
      each side, so the sum of on-ice Corsi for over all players equals the sum of Corsi against;
   2. that sum equals five times the teams' 5v5 attempts in team_game_strength;
   3. no off-ice count is negative (the team's count can never be less than the player's).
C. A glance: the 5v5 leaders by Corsi % and the most extreme relative values, to read with an
   eye for anything odd.
"""

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data" / "raw"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
STRENGTH_FIELDS = {"ev": "evTimeOnIce", "pp": "ppTimeOnIce", "sh": "shTimeOnIce"}
ATTEMPT_KINDS = ("goal", "sog", "miss", "block")


def bucket(diff):
    diff = abs(diff)
    for limit, name in ((0, "exact"), (2, "<=2 s"), (10, "<=10 s"), (60, "<=60 s")):
        if diff <= limit:
            return name
    return ">60 s"


def main():
    parser = argparse.ArgumentParser(description="Check the advanced on-ice skater table.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    metrics = METRICS_ROOT / f"season={args.season}"

    rows = pq.read_table(metrics / "player_season_advanced.parquet").to_pylist()
    team_rows = [r for r in rows if r["kind"] == "team"]

    print(f"Season {args.season}: {len(rows)} rows, {len(team_rows)} player-team-situation rows")

    with gzip.open(RAW_ROOT / f"season={args.season}" / "reference" / "skater_timeonice.json.gz", "rb") as handle:
        reference = {r["playerId"]: r for r in json.loads(handle.read())["data"]}
    seconds = defaultdict(Counter)
    for row in team_rows:
        seconds[row["player_id"]][row["situation"]] += row["seconds"]
    order = ["exact", "<=2 s", "<=10 s", "<=60 s", ">60 s"]
    print(f"\nA. Time on ice by strength vs the NHL ({len(reference)} skaters; the NHL's is for all games, ours for games with shifts)")
    print(f"{'strength':9s}" + "".join(f"{b:>9s}" for b in order) + f"{'our total':>12s}{'NHL total':>12s}{'diff %':>9s}")
    for strength, field in STRENGTH_FIELDS.items():
        counts = dict.fromkeys(order, 0)
        ours_total = nhl_total = 0
        for player_id, ref in reference.items():
            value = seconds[player_id][strength]
            ours_total += value
            nhl_total += ref[field]
            counts[bucket(value - ref[field])] += 1
        print(f"{strength:9s}" + "".join(f"{counts[b]:>9d}" for b in order)
              + f"{ours_total:>12d}{nhl_total:>12d}{100 * (ours_total - nhl_total) / nhl_total:>8.2f}%")

    five = [r for r in team_rows if r["situation"] == "5v5"]
    cf, ca = sum(r["cf"] for r in five), sum(r["ca"] for r in five)
    team_game = pq.read_table(metrics / "team_game_strength.parquet").to_pylist()
    team_for = sum(
        sum(r[f"for_{k}"] for k in ATTEMPT_KINDS) for r in team_game
        if (r["strength"], r["skaters_for"], r["skaters_against"], r["goalies_for"], r["goalies_against"]) == ("ev", 5, 5, 1, 1)
    )
    negative = sum(1 for r in rows if any(r[c] < 0 for c in r if c.startswith("off_") and isinstance(r[c], int)))
    print("\nB. Identities at 5v5")
    print(f"  1. on-ice Corsi for {cf}, against {ca}: {'equal' if cf == ca else 'NOT equal, difference ' + str(cf - ca)}")
    print(f"  2. Corsi for {cf} vs 5 x team attempts {5 * team_for}: {'equal' if cf == 5 * team_for else 'NOT equal, difference ' + str(cf - 5 * team_for)}")
    print(f"  3. rows with a negative off-ice count: {negative}")

    shown = [r for r in five if (r["kind"] == "total" or r["teams"] == r["team"]) and r["seconds"] >= 600 * 60]
    print(f"\nC. 5v5, players with at least 600 minutes: {len(shown)}")
    print("  highest CF%:")
    for r in sorted(shown, key=lambda r: -r["cf_pct"])[:5]:
        print(f"    {r['name']:24s} {r['team']:4s} CF% {r['cf_pct']:5.1f}  rel {r['cf_pct_rel']:+5.1f}  TOI {r['seconds'] / 60:7.1f}")
    print("  lowest CF%:")
    for r in sorted(shown, key=lambda r: r["cf_pct"])[:5]:
        print(f"    {r['name']:24s} {r['team']:4s} CF% {r['cf_pct']:5.1f}  rel {r['cf_pct_rel']:+5.1f}  TOI {r['seconds'] / 60:7.1f}")
    rels = sorted(r["cf_pct_rel"] for r in shown if r["cf_pct_rel"] is not None)
    print(f"  CF% rel: lowest {rels[0]:+.1f}, median {rels[len(rels) // 2]:+.1f}, highest {rels[-1]:+.1f}")


if __name__ == "__main__":
    main()