"""Download the NHL's own season reports. They are used only to check our numbers.

Run from the repo root with the `nhl` conda environment active:

    python src/nhl_pipeline/ingest/ingest_reference.py --season 2023

Saves, for the regular season, each response exactly as received, in data/raw/season=2023/reference/:
    skater_timeonice.json.gz   one row per skater: total, even-strength, power-play and shorthanded
                               time on ice in seconds, shifts and games played
    goalie_summary.json.gz     one row per goalie: games played and started, wins, losses, overtime
                               losses, shots against, saves, goals against, save percentage,
                               goals-against average, shutouts, time on ice
    skater_faceoffs.json.gz    one row per skater: faceoffs won and lost, in total and by strength and zone
    skater_powerplay.json.gz   one row per skater: power-play time on ice, goals, assists, points
    skater_penaltykill.json.gz one row per skater: penalty-kill time on ice, shorthanded goals and points
    team_powerplay.json.gz     one row per team: power-play opportunities, goals and percentage
    team_penaltykill.json.gz   one row per team: times shorthanded, goals against and percentage
    team_powerplay_games.json.gz   the same power-play report with one row per team and game
    team_penaltykill_games.json.gz the same penalty-kill report with one row per team and game
"""

import argparse
import json
import sys
from pathlib import Path

from endpoints import STATS_BASE, Fetcher
from rawstore import reference_path, write_gz_atomic

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_ROOT = REPO_ROOT / "data" / "raw"
REPORTS = {  # file name -> path of the report under STATS_BASE
    "skater_timeonice": "skater/timeonice",
    "goalie_summary": "goalie/summary",
    "skater_faceoffs": "skater/faceoffpercentages",
    "skater_powerplay": "skater/powerplay",
    "skater_penaltykill": "skater/penaltykill",
    "team_powerplay": "team/powerplay",
    "team_penaltykill": "team/penaltykill",
}
GAME_REPORTS = {  # the same reports with one row per team and game (isGame=true)
    "team_powerplay_games": "team/powerplay",
    "team_penaltykill_games": "team/penaltykill",
}


def download_report(fetcher, season, name, endpoint, raw_root, per_game=False):
    """Download one report for the regular season and save it; exit if the NHL's answer is incomplete.
    With `per_game` the report has one row per team and game instead of one per season."""
    season_id = f"{season}{season + 1}"
    response = fetcher.get(
        f"{STATS_BASE}/{endpoint}",
        params={
            "isAggregate": "false",
            "isGame": "true" if per_game else "false",
            "limit": -1,
            "start": 0,
            "cayenneExp": f"seasonId={season_id} and gameTypeId=2",
        },
    )
    if response.status_code != 200:
        sys.exit(f"The NHL answered {response.status_code} for {name}; nothing was saved for it.")
    body = json.loads(response.content)
    rows, total = len(body["data"]), body["total"]
    if rows != total:
        sys.exit(f"Got {rows} rows but the NHL reports {total} for {name}; nothing was saved for it.")
    path = reference_path(raw_root, season, name)
    write_gz_atomic(path, response.content)
    print(f"Saved {rows} rows of {name} to {path}")


def main():
    parser = argparse.ArgumentParser(description="Download the NHL's season reports.")
    parser.add_argument("--season", type=int, required=True, help="start year, 2023 = 2023-24")
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--min-interval", type=float, default=1.0)
    args = parser.parse_args()

    fetcher = Fetcher(min_interval=args.min_interval)
    for name, endpoint in REPORTS.items():
        download_report(fetcher, args.season, name, endpoint, args.raw_root)
    for name, endpoint in GAME_REPORTS.items():
        download_report(fetcher, args.season, name, endpoint, args.raw_root, per_game=True)


if __name__ == "__main__":
    main()