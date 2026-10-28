"""Phase 1: download the raw files for one regular season.

Run from the repo root with the `nhl` conda environment active:

    python src/nhl_pipeline/ingest/ingest_season.py --season 2023 --dry-run
    python src/nhl_pipeline/ingest/ingest_season.py --season 2023 --limit 20
    python src/nhl_pipeline/ingest/ingest_season.py --season 2023

--season is the year the season starts (2023 means 2023-24).

How it works:
  1. Walk the weekly league schedule to list every game in the season.
  2. Keep regular-season games that are finished and not postponed.
  3. For each game, fetch play-by-play, boxscore and shift chart, and save each
     response exactly as received (gzipped). Files that already exist are
     skipped, so a rerun only fetches what is missing and an interrupted run
     can simply be started again.
  4. Append one line per fetch outcome to the ingestion log.

A response is saved only if it contains real data. If the NHL returns a shift
chart with no rows at all (it does this for some games), a marker file is
written instead and the game counts as loaded without shift data. Those games
are not retried unless you pass --recheck-empty.
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from endpoints import MIN_INTERVAL_SECONDS, Fetcher, game_requests, schedule_url
from rawstore import (
    clear_empty_marker,
    game_is_complete,
    has_empty_marker,
    raw_path,
    schedule_path,
    write_empty_marker,
    write_gz_atomic,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_ROOT = REPO_ROOT / "data" / "raw"
DEFAULT_LOG_PATH = REPO_ROOT / "data" / "logs" / "ingestion_log.jsonl"

REGULAR_SEASON = 2  # the game-type digits of the game ID
FINISHED_STATES = ("OFF", "FINAL")  # confirm against the dry-run output
MAX_WEEKS = 60  # safety stop for the schedule walk

VALIDATORS = {
    "play-by-play": lambda d: isinstance(d, dict) and bool(d.get("plays")),
    "boxscore": lambda d: isinstance(d, dict) and "playerByGameStats" in d,
    "shiftcharts": lambda d: isinstance(d, dict) and bool(d.get("data")),
}


def season_of(game_id):
    """2023020001 -> 2023 (the year the season starts)."""
    return int(str(game_id)[:4])


def game_type_of(game_id):
    """2023020001 -> 2 (01 preseason, 02 regular season, 03 playoffs)."""
    return int(str(game_id)[4:6])


def log_event(log_path, **fields):
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def list_season_games(fetcher, start, end, on_week=None):
    """Walk the weekly schedule from `start`, following nextStartDate up to `end`.

    Returns {game_id: {"date", "state", "schedule_state"}}. A game that appears
    in two weekly responses keeps its latest entry. `on_week(date, content)` is
    called with each raw response, so the caller can save it.
    """
    games = {}
    date = start
    for _ in range(MAX_WEEKS):
        response = fetcher.get(schedule_url(date))
        if response.status_code != 200:
            raise RuntimeError(
                f"Schedule call failed with HTTP {response.status_code}: "
                f"{schedule_url(date)}"
            )
        if on_week:
            on_week(date, response.content)
        data = json.loads(response.content)
        for day in data.get("gameWeek", []):
            for game in day.get("games", []):
                games[int(game["id"])] = {
                    "date": day.get("date"),
                    "state": game.get("gameState"),
                    "schedule_state": game.get("gameScheduleState"),
                }
        next_date = data.get("nextStartDate")
        if not next_date or next_date > end or next_date <= date:
            break
        date = next_date
    else:
        raise RuntimeError("Schedule walk did not finish; check --start and --end.")
    return games


def select_games(games, season, states=FINISHED_STATES):
    """Regular-season games of `season` that are finished and not postponed."""
    chosen = []
    for game_id, info in games.items():
        if season_of(game_id) != season or game_type_of(game_id) != REGULAR_SEASON:
            continue
        if info["state"] not in states:
            continue
        if info["schedule_state"] not in (None, "OK"):
            continue
        chosen.append(game_id)
    return sorted(chosen)


def fetch_one(fetcher, raw_root, season, game_id, name, url, params, log_path):
    """Fetch one endpoint and save it.

    Returns "saved" if the file was saved, "empty" if the NHL returned a shift
    chart with no rows (a marker is written), or None if the fetch failed.
    """
    log = {"season": season, "game_id": game_id, "endpoint": name}
    try:
        response = fetcher.get(url, params)
    except Exception as exc:  # network failure that survived the retries
        log_event(log_path, **log, status="error", detail=repr(exc))
        return None
    if response.status_code != 200:
        log_event(
            log_path,
            **log,
            status=f"http_{response.status_code}",
            http_status=response.status_code,
        )
        return None
    try:
        data = json.loads(response.content)
    except ValueError:
        log_event(log_path, **log, status="invalid", detail="response is not JSON")
        return None
    if (
        name == "shiftcharts"
        and isinstance(data, dict)
        and data.get("data") == []
    ):
        write_empty_marker(
            raw_root, season, game_id, datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        log_event(log_path, **log, status="empty", detail="NHL returned no shift rows")
        return "empty"
    if not VALIDATORS[name](data):
        log_event(
            log_path, **log, status="invalid", detail="empty or missing expected fields"
        )
        return None
    write_gz_atomic(raw_path(raw_root, season, game_id, name), response.content)
    if name == "shiftcharts":
        clear_empty_marker(raw_root, season, game_id)
    log_event(log_path, **log, status="saved", bytes=len(response.content))
    return "saved"


def ingest_game(fetcher, raw_root, season, game_id, log_path, recheck_empty=False):
    """Fetch whatever is missing for one game.

    Returns True if the game is now complete (see game_is_complete). Files
    already on disk are not fetched again, and a game whose shift chart is
    known to be empty is not asked again unless `recheck_empty` is True.
    """
    complete = True
    for name, url, params in game_requests(game_id):
        if raw_path(raw_root, season, game_id, name).exists():
            continue
        if (
            name == "shiftcharts"
            and has_empty_marker(raw_root, season, game_id)
            and not recheck_empty
        ):
            continue
        if fetch_one(
            fetcher, raw_root, season, game_id, name, url, params, log_path
        ) is None:
            complete = False
    return complete


def main():
    parser = argparse.ArgumentParser(
        description="Download the raw NHL files for one regular season."
    )
    parser.add_argument(
        "--season", type=int, required=True, help="start year, e.g. 2023 for 2023-24"
    )
    parser.add_argument("--start", help="first schedule date; default Oct 1 of the season")
    parser.add_argument("--end", help="last schedule date; default Apr 30 of the next year")
    parser.add_argument("--limit", type=int, help="try at most this many games this run")
    parser.add_argument(
        "--dry-run", action="store_true", help="list the games, download nothing"
    )
    parser.add_argument(
        "--states",
        default=",".join(FINISHED_STATES),
        help="gameState values that count as finished",
    )
    parser.add_argument(
        "--recheck-empty",
        action="store_true",
        help="ask again for games whose shift chart the NHL returned empty",
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument(
        "--min-interval",
        type=float,
        default=MIN_INTERVAL_SECONDS,
        help="seconds between requests; keep this polite",
    )
    args = parser.parse_args()

    start = args.start or f"{args.season}-10-01"
    end = args.end or f"{args.season + 1}-04-30"
    states = tuple(s.strip() for s in args.states.split(",") if s.strip())
    fetcher = Fetcher(min_interval=args.min_interval)

    on_week = None
    if not args.dry_run:

        def on_week(date, content):
            write_gz_atomic(schedule_path(args.raw_root, args.season, date), content)

    print(f"Walking the schedule from {start} to {end} ...")
    try:
        games = list_season_games(fetcher, start, end, on_week)
    except RuntimeError as exc:
        sys.exit(str(exc))

    regular = {
        game_id: info
        for game_id, info in games.items()
        if season_of(game_id) == args.season and game_type_of(game_id) == REGULAR_SEASON
    }
    selected = select_games(games, args.season, states)
    todo = [
        g
        for g in selected
        if not game_is_complete(args.raw_root, args.season, g)
        or (args.recheck_empty and has_empty_marker(args.raw_root, args.season, g))
    ]
    no_shifts = [
        g for g in selected if has_empty_marker(args.raw_root, args.season, g)
    ]

    print(f"Games in the schedule responses: {len(games)}")
    print(f"Regular-season games for {args.season}: {len(regular)}")
    print(f"  gameState counts: {dict(Counter(i['state'] for i in regular.values()))}")
    print(
        "  gameScheduleState counts: "
        f"{dict(Counter(i['schedule_state'] for i in regular.values()))}"
    )
    print(f"Selected as finished: {len(selected)} (states: {', '.join(states)})")
    print(f"Already complete on disk: {len(selected) - len(todo)}")
    print(f"  with no shift data (NHL returns none): {len(no_shifts)}")
    print(f"To download: {len(todo)}")
    if todo:
        minutes = len(todo) * 3 * args.min_interval / 60
        print(f"At least {minutes:.0f} minutes at {args.min_interval}s between requests.")

    if args.dry_run:
        print("Dry run: nothing downloaded.")
        return
    if not selected:
        sys.exit("No finished games selected. Check the state counts and use --states.")

    started = time.monotonic()
    attempted = 0
    downloaded = 0
    incomplete = []
    try:
        for index, game_id in enumerate(todo, start=1):
            if args.limit is not None and attempted >= args.limit:
                break
            ok = ingest_game(
                fetcher,
                args.raw_root,
                args.season,
                game_id,
                args.log,
                recheck_empty=args.recheck_empty,
            )
            attempted += 1
            if ok:
                downloaded += 1
            else:
                incomplete.append(game_id)
            print(f"[{index}/{len(todo)}] {game_id} {'ok' if ok else 'INCOMPLETE'}")
    except KeyboardInterrupt:
        print("\nInterrupted. Rerun the same command to resume.")

    minutes = (time.monotonic() - started) / 60
    print(
        f"\nFinished in {minutes:.1f} min: {downloaded} downloaded, "
        f"{len(incomplete)} incomplete."
    )
    still_empty = sum(has_empty_marker(args.raw_root, args.season, g) for g in selected)
    print(f"Games with no shift data from the NHL: {still_empty}")
    if incomplete:
        print(f"Incomplete games (details in {args.log}): {incomplete}")
        print("Rerun the same command to retry them.")


if __name__ == "__main__":
    main()