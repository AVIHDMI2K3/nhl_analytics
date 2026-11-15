"""Do the NHL's HTML shift reports agree with the shift-chart API on games that have both? (Phase 5)

For each game given, fetches (and caches in data/scratch/) the home and visitor time-on-ice reports, turns them into
shift rows with shift_reports.py (players matched to ids by jersey number through the boxscore), and compares them
with the API shifts in staging: per player, the number of shifts, the total seconds on the ice, and how many shifts
have exactly the same start and end second. If they agree, the reports can stand in for the 57 games of 2024-25 the
API has no shifts for. Run from the repo root with the `nhl` environment active:

    python scripts/compare_html_shifts.py --season 2024 --games 2024020913 2024020100 2024020500 2024021000

Prints one line per game and the players that differ most. Reads staging, writes only the cached pages.
"""

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_html_shift_reports import HEADERS, report_url  # noqa: E402
from shift_reports import parse_report, shift_rows  # noqa: E402

SCRATCH = REPO_ROOT / "data" / "scratch"


def fetch(game_id, side, pause):
    """Text of one report, from data/scratch if already saved, otherwise downloaded (and saved)."""
    import requests

    path = SCRATCH / f"{side}{str(game_id)[4:]}_{str(game_id)[:4]}.HTM"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    response = requests.get(report_url(game_id, side), headers=HEADERS, timeout=30)
    response.raise_for_status()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    time.sleep(pause)
    return response.content.decode("utf-8", errors="replace")


def compare_players(api_rows, html_rows):
    """{player_id: (api shifts, html shifts, api seconds, html seconds, identical shifts)} for the players in either."""
    def by_player(rows):
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["player_id"]].append((row["start_game_seconds"], row["end_game_seconds"]))
        return grouped

    api, html = by_player(api_rows), by_player(html_rows)
    result = {}
    for player in set(api) | set(html):
        a, h = api.get(player, []), html.get(player, [])
        result[player] = (len(a), len(h), sum(e - s for s, e in a), sum(e - s for s, e in h), len(set(a) & set(h)))
    return result


def main():
    parser = argparse.ArgumentParser(description="Compare HTML shift reports with the API shifts in staging.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--games", type=int, nargs="+", required=True)
    parser.add_argument("--pause", type=float, default=3.0)
    args = parser.parse_args()
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    staging = REPO_ROOT / "data" / "staging" / f"season={args.season}"
    shifts = pq.read_table(staging / "shifts.parquet", columns=[
        "game_id", "player_id", "team_id", "period", "start_game_seconds", "end_game_seconds"])
    box = pq.read_table(staging / "boxscore_players.parquet",
                        columns=["game_id", "team_id", "home_or_away", "player_id", "sweater_number"])
    for game_id in args.games:
        api = pc.filter(shifts, pc.equal(shifts["game_id"], game_id)).to_pylist()
        players = pc.filter(box, pc.equal(box["game_id"], game_id)).to_pylist()
        html_rows, unmatched, team_ids = [], [], {}
        for side, home_or_away in (("TH", "home"), ("TV", "away")):
            ids = {p["sweater_number"]: p["player_id"] for p in players if p["home_or_away"] == home_or_away}
            team_ids[side] = next((p["team_id"] for p in players if p["home_or_away"] == home_or_away), None)
            rows, missing = shift_rows(game_id, team_ids[side], parse_report(fetch(game_id, side, args.pause)), ids)
            html_rows += rows
            unmatched += missing
        compared = compare_players(api, html_rows)
        identical = sum(v[4] for v in compared.values())
        print(f"{game_id}: API {len(api)} shifts, HTML {len(html_rows)}; identical start/end in {identical}; "
              f"players with different shift counts {sum(v[0] != v[1] for v in compared.values())}; "
              f"different seconds {sum(v[2] != v[3] for v in compared.values())}; "
              f"HTML players without an id {unmatched}")
        for player, (na, nh, sa, sh, same) in sorted(compared.items(), key=lambda i: -abs(i[1][2] - i[1][3]))[:3]:
            if sa != sh:
                print(f"    player {player}: shifts API {na} HTML {nh}, seconds API {sa} HTML {sh}, identical {same}")


if __name__ == "__main__":
    main()