"""Compare one skater's time on ice, game by game, with the NHL's own per-game numbers.

Run from the repo root with the `nhl` conda environment active, after stage_season.py:

    python scripts/compare_player_games.py --season 2023 --player 8475181

Read-only. It asks the NHL stats service for the skater's per-game time on ice and shift
count, applies the shift-number rule to the staged shifts (go through each period's shifts
in shift-number order and drop any that overlaps one already kept), compares the two game
by game, and prints every staged shift row, kept or dropped, in the two games that differ
most. Use it to see what the rule still gets wrong.
"""

import argparse
from collections import defaultdict
from pathlib import Path

import duckdb
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
URL = "https://api.nhle.com/stats/rest/en/skater/timeonice"
USER_AGENT = "nhl-analytics-portfolio/0.1 (personal project)"
BIG = 10**9


def fetch_games(player_id, season):
    response = requests.get(
        URL,
        params={
            "isAggregate": "false",
            "isGame": "true",
            "limit": -1,
            "start": 0,
            "cayenneExp": f"playerId={player_id} and seasonId={season}{season + 1} and gameTypeId=2",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return {row["gameId"]: row for row in response.json()["data"]}


def overlaps(start, end, kept_start, kept_end):
    if start == kept_start and end == kept_end:
        return True
    return start < kept_end and kept_start < end


def mark_kept(rows):
    """rows: dicts for one game. Adds row['kept'] using the shift-number rule, per period."""
    by_period = defaultdict(list)
    for row in rows:
        by_period[row["period"]].append(row)
    for period_rows in by_period.values():
        period_rows.sort(
            key=lambda r: (
                BIG if r["shift_number"] is None else r["shift_number"],
                BIG if r["shift_id"] is None else r["shift_id"],
            )
        )
        kept = []
        for row in period_rows:
            row["kept"] = not any(overlaps(row["start"], row["end"], ks, ke) for ks, ke in kept)
            if row["kept"]:
                kept.append((row["start"], row["end"]))


def main():
    parser = argparse.ArgumentParser(description="Compare one skater's games with the NHL's.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--player", type=int, required=True)
    args = parser.parse_args()

    nhl = fetch_games(args.player, args.season)
    shifts_path = (STAGING_ROOT / f"season={args.season}" / "shifts.parquet").as_posix()
    staged = (
        duckdb.connect()
        .execute(
            f"""
        select game_id, period, shift_number, shift_id,
               start_game_seconds, end_game_seconds, duration_seconds
        from '{shifts_path}'
        where player_id = {args.player}
          and start_game_seconds is not null and end_game_seconds is not null
        """
        )
        .fetchall()
    )

    games = defaultdict(list)
    for game_id, period, number, shift_id, start, end, duration in staged:
        games[game_id].append(
            {
                "period": period,
                "shift_number": number,
                "shift_id": shift_id,
                "start": start,
                "end": end,
                "duration": duration,
            }
        )

    differences = []
    for game_id, rows in games.items():
        mark_kept(rows)
        kept = [r for r in rows if r["kept"]]
        our_toi = sum(r["end"] - r["start"] for r in kept)
        ref = nhl.get(game_id)
        if ref is None:
            differences.append((BIG, game_id, our_toi, None, len(kept), None))
            continue
        toi_diff, shift_diff = our_toi - ref["timeOnIce"], len(kept) - ref["shifts"]
        if toi_diff or shift_diff:
            differences.append((abs(toi_diff), game_id, our_toi, ref["timeOnIce"], len(kept), ref["shifts"]))

    print(f"{len(nhl)} games in the NHL's data, {len(games)} with staged shifts")
    print("\nGames that differ (ours minus NHL), largest first")
    print("game_id      our_toi  nhl_toi  toi_diff  our_shifts  nhl_shifts  shift_diff")
    differences.sort(reverse=True)
    for _, game_id, our_toi, nhl_toi, our_n, nhl_n in differences:
        if nhl_toi is None:
            print(f"{game_id}  {our_toi:>7}  (not in the NHL's data)")
            continue
        print(
            f"{game_id}  {our_toi:>7}  {nhl_toi:>7}  {our_toi - nhl_toi:>8}  "
            f"{our_n:>10}  {nhl_n:>10}  {our_n - nhl_n:>10}"
        )

    for _, game_id, *_ in differences[:2]:
        print(f"\nStaged shifts in game {game_id}")
        print("period  shift_no  shift_id    start    end  length  kept")
        for row in sorted(games[game_id], key=lambda r: (r["period"], r["start"], r["end"])):
            print(
                f"{row['period']:>6}  {str(row['shift_number']):>8}  {str(row['shift_id']):>8}  "
                f"{row['start']:>6}  {row['end']:>5}  {row['end'] - row['start']:>6}  "
                f"{'yes' if row['kept'] else 'DROPPED'}"
            )


if __name__ == "__main__":
    main()
