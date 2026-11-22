"""Check the skater season totals (Phase 4.5) against the NHL's own season numbers.

Run from the repo root with the `nhl` conda environment active, after build_season_totals.py:

    python scripts/check_season_totals.py --season 2025

Compares, per skater (all teams added up), the games played and total time on ice with the
NHL's skater time-on-ice report (data/raw/season=YYYY/reference/skater_timeonice.json.gz).
Shows both ways of counting games played so we can see which one the NHL uses: every game the
skater is listed in, or only games in which he had time on ice.
"""

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data" / "raw"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
TIME_FIELDS = ("evTimeOnIce", "ppTimeOnIce", "shTimeOnIce")


def main():
    parser = argparse.ArgumentParser(description="Check the skater season totals.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    with gzip.open(RAW_ROOT / f"season={args.season}" / "reference" / "skater_timeonice.json.gz", "rb") as handle:
        reference = {r["playerId"]: r for r in json.loads(handle.read())["data"]}
    print(f"Fields in the NHL report: {sorted(next(iter(reference.values())))}")

    totals = pq.read_table(METRICS_ROOT / f"season={args.season}" / "player_season_totals.parquet").to_pylist()
    ours = defaultdict(Counter)
    for row in totals:
        ours[row["player_id"]]["games"] += row["games_played"]
        ours[row["player_id"]]["toi"] += row["toi_seconds"]
    box = pq.read_table(
        STAGING_ROOT / f"season={args.season}" / "boxscore_players.parquet",
        columns=["game_id", "player_id", "player_group", "toi_seconds"],
    ).to_pylist()
    with_ice = defaultdict(set)
    for row in box:
        if row["player_group"] != "goalies" and (row["toi_seconds"] or 0) > 0:
            with_ice[row["player_id"]].add(row["game_id"])

    print(
        f"\nNHL skaters: {len(reference)}; ours: {len(ours)}; "
        f"in the NHL report but not ours: {len(set(reference) - set(ours))}; "
        f"ours but not the NHL's: {len(set(ours) - set(reference))}"
    )
    games_listed = games_with_ice = toi_exact = toi_close = compared = 0
    toi_ours = toi_nhl = 0
    worst = []
    for player_id, ref in reference.items():
        if player_id not in ours:
            continue
        compared += 1
        nhl_games = ref.get("gamesPlayed")
        games_listed += ours[player_id]["games"] == nhl_games
        games_with_ice += len(with_ice[player_id]) == nhl_games
        nhl_toi = sum(ref[f] for f in TIME_FIELDS)
        diff = ours[player_id]["toi"] - nhl_toi
        toi_exact += diff == 0
        toi_close += abs(diff) <= 2
        toi_ours += ours[player_id]["toi"]
        toi_nhl += nhl_toi
        worst.append((abs(diff), player_id, ours[player_id]["toi"], nhl_toi))
    print(f"\nGames played equal to the NHL's, of {compared} skaters:")
    print(f"  counting every game he is listed in:      {games_listed}")
    print(f"  counting only games with time on ice:     {games_with_ice}")
    print(f"Total time on ice equal to the NHL's: {toi_exact} exactly, {toi_close} within 2 s")
    print(f"  all skaters: ours {toi_ours}, NHL {toi_nhl}, difference {toi_ours - toi_nhl:+d} s")
    for diff, player_id, ours_value, nhl_value in sorted(worst, reverse=True)[:5]:
        print(f"  largest gap: player {player_id} ours {ours_value} NHL {nhl_value}")


if __name__ == "__main__":
    main()
