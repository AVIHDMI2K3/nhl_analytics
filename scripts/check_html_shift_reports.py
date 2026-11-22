"""Does the NHL's HTML time-on-ice report exist for games whose shift chart the API leaves empty?

The NHL publishes, for each game, one report per team: TH (home) and TV (visitor), at
https://www.nhl.com/scores/htmlreports/<season>/TH<six digits>.HTM. 57 games in 2024-25 (ids 2024021235 to 2024021291)
have no shifts from the API. This fetches the two reports for a few of them, and for one game that does have API shifts
as a control, and prints for each: the HTTP status, the size, and how many players and shift rows the page holds. It
reads the pages only; nothing is written. Run from the repo root with the `nhl` environment active:

    python scripts/check_html_shift_reports.py
    python scripts/check_html_shift_reports.py --games 2024021240 2024021250

One request every few seconds, one run, a handful of pages.
"""

import argparse
import re
import time

import requests

DEFAULT_GAMES = [2024021235, 2024021263, 2024021291, 2024020913]  # three missing ones and a control with API shifts
HEADERS = {"User-Agent": "nhl-analytics-portfolio (personal research; contact via GitHub)"}


def report_url(game_id, side):
    """URL of the home ('TH') or visitor ('TV') report of a game, e.g. 2024021235 -> .../20242025/TH021235.HTM."""
    start = int(str(game_id)[:4])
    return f"https://www.nhl.com/scores/htmlreports/{start}{start + 1}/{side}{str(game_id)[4:]}.HTM"


def summarize(html):
    """(players, shift rows) found in a time-on-ice report: one 'playerHeading' cell per player, shifts in rows with
    a shift number, a period, a start and end time and a duration."""
    players = len(re.findall(r'class="[^"]*playerHeading', html))
    shifts = len(re.findall(r"\d{1,2}:\d{2}\s*/\s*\d{1,2}:\d{2}", html))
    return players, shifts


def main():
    parser = argparse.ArgumentParser(description="Check for NHL HTML shift reports.")
    parser.add_argument("--games", type=int, nargs="+", default=DEFAULT_GAMES)
    parser.add_argument("--pause", type=float, default=3.0, help="seconds between requests")
    args = parser.parse_args()
    for game_id in args.games:
        for side, label in (("TH", "home"), ("TV", "visitor")):
            url = report_url(game_id, side)
            try:
                response = requests.get(url, headers=HEADERS, timeout=30)
                players, shifts = summarize(response.text)
                print(
                    f"{game_id} {label:7s} HTTP {response.status_code}  {len(response.content):7d} bytes  "
                    f"{players:3d} players  {shifts:5d} shift rows   {url}"
                )
            except requests.RequestException as error:
                print(f"{game_id} {label:7s} request failed: {error}")
            time.sleep(args.pause)


if __name__ == "__main__":
    main()
