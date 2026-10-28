"""Phase 0 probe: call each NHL endpoint once for one game and save the raw responses.

Goal of this script (the Phase 0 gate): confirm the response shapes before any
tables are designed. It saves every response exactly as received and prints a
short summary of what each one contains.

Run from the repo root with the `nhl` conda environment active:

    python src/nhl_pipeline/ingest/probe.py
    python src/nhl_pipeline/ingest/probe.py --game-id 2024020240

Game ID format: season start year + 2-digit game type (02 = regular season)
+ 4-digit game number, e.g. 2023021148 is a 2023-24 regular-season game.
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

WEB_BASE = "https://api-web.nhle.com/v1"
STATS_BASE = "https://api.nhle.com/stats/rest/en"
DEFAULT_GAME_ID = 2023021148
PAUSE_SECONDS = 1.0  # polite gap between calls
USER_AGENT = "nhl-analytics-portfolio/0.1 (personal project)"

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "raw" / "phase0"


class RetryableHTTPError(Exception):
    """Server-side or rate-limit error worth retrying."""


@retry(
    retry=retry_if_exception_type(
        (requests.ConnectionError, requests.Timeout, RetryableHTTPError)
    ),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def fetch(session, url, params=None):
    response = session.get(url, params=params, timeout=30)
    if response.status_code >= 500 or response.status_code == 429:
        raise RetryableHTTPError(f"{response.status_code} from {response.url}")
    response.raise_for_status()
    return response


def save_raw(out_dir, name, response):
    """Save the response exactly as received."""
    path = out_dir / name
    path.write_text(response.text, encoding="utf-8")
    print(f"  saved {path} ({len(response.content):,} bytes)")
    return path


def check_keys(label, data, expected):
    for key in expected:
        status = "ok     " if key in data else "MISSING"
        print(f"  [{status}] {label}.{key}")


def summarize_play_by_play(data):
    print("\nPLAY-BY-PLAY")
    print(f"  top-level keys: {sorted(data.keys())}")
    check_keys("pbp", data, ["id", "plays", "rosterSpots", "homeTeam", "awayTeam"])
    plays = data.get("plays", [])
    print(f"  plays: {len(plays)}")
    counts = Counter(p.get("typeDescKey") for p in plays)
    print(f"  event types: {dict(counts.most_common())}")
    if plays:
        print(f"  keys on a play: {sorted(plays[0].keys())}")
        print(f"  sample situationCode: {plays[0].get('situationCode')}")
    # One sample per event type (first occurrence), so every type's detail
    # fields are visible: shots, blocked shots, giveaways, takeaways, hits, etc.
    samples = {}
    for p in plays:
        samples.setdefault(p.get("typeDescKey"), p)
    print(f"\n  ONE SAMPLE PER EVENT TYPE ({len(samples)} types)")
    for key, p in samples.items():
        print(f"  - {key}: detail keys {sorted(p.get('details', {}).keys())}")
        print(f"    {json.dumps(p)[:600]}")
    print(f"\n  rosterSpots: {len(data.get('rosterSpots', []))}")


def summarize_boxscore(data):
    print("\nBOXSCORE")
    print(f"  top-level keys: {sorted(data.keys())}")
    check_keys("boxscore", data, ["id", "homeTeam", "awayTeam", "playerByGameStats"])
    stats = data.get("playerByGameStats", {})
    for side in ("homeTeam", "awayTeam"):
        team = stats.get(side, {})
        sizes = {k: len(v) for k, v in team.items() if isinstance(v, list)}
        print(f"  playerByGameStats.{side}: {sizes}")


def summarize_shifts(data):
    print("\nSHIFT CHART")
    print(f"  top-level keys: {sorted(data.keys())}")
    rows = data.get("data", [])
    print(f"  rows: {len(rows)} (reported total: {data.get('total')})")
    if rows:
        print(f"  keys on a row: {sorted(rows[0].keys())}")
        print(f"  sample row: {json.dumps(rows[0])}")
        print(f"  typeCode counts: {dict(Counter(r.get('typeCode') for r in rows))}")
        print(f"  distinct players: {len({r.get('playerId') for r in rows})}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--game-id", type=int, default=DEFAULT_GAME_ID)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    game_id = args.game_id
    print(f"Game {game_id} -> {args.out}")

    calls = [
        (
            "play-by-play",
            f"{WEB_BASE}/gamecenter/{game_id}/play-by-play",
            None,
            summarize_play_by_play,
        ),
        (
            "boxscore",
            f"{WEB_BASE}/gamecenter/{game_id}/boxscore",
            None,
            summarize_boxscore,
        ),
        (
            "shiftcharts",
            f"{STATS_BASE}/shiftcharts",
            {"cayenneExp": f"gameId={game_id}"},
            summarize_shifts,
        ),
    ]

    with requests.Session() as session:
        session.headers.update({"User-Agent": USER_AGENT})
        for i, (name, url, params, summarize) in enumerate(calls):
            if i:
                time.sleep(PAUSE_SECONDS)
            print(f"\nFetching {name} ...")
            response = fetch(session, url, params)
            save_raw(args.out, f"{game_id}_{name}.json", response)
            summarize(response.json())

    print("\nDone. Phase 0 gate: sample responses saved and shapes confirmed.")


if __name__ == "__main__":
    main()
