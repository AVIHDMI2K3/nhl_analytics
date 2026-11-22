"""Compare our boxscore data with the NHL's official game summary pages.

Run from the repo root with the `nhl` conda environment active (needs internet):

    python scripts/compare_boxscore_to_nhl.py --season 2025 --games 1 --show
    python scripts/compare_boxscore_to_nhl.py --season 2025 --games 20

Our boxscore numbers come from the api-web.nhle.com service (data/staging/.../boxscore_players
.parquet). The official game summary is the HTML page on nhl.com
(https://www.nhl.com/scores/htmlreports/<season>/ES<6 digits>.HTM, the event summary, which is
the report with one row per player; the game summary GS has no per-player table). This script
downloads that page for a random sample of regular-season games, reads the skater table, and counts how many
player values are identical in the two sources.

IMPORTANT: the page layout was not seen when this was written. The script finds the skater
tables by their header row (the one containing "+/-"), maps columns by header name, and says
which headers it used and which it could not use. Run it with --games 1 --show first and check
that the printed header and first player row look right before trusting the totals.
Pages are cached in data/nhl_compare/ so each is downloaded once.
Writes data/logs/compare_boxscore_to_nhl.json.
"""

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
CACHE_DIR = REPO_ROOT / "data" / "nhl_compare"
LOG_DIR = REPO_ROOT / "data" / "logs"
URL = "https://www.nhl.com/scores/htmlreports/{season}{next_season}/{report}{number:06d}.HTM"
USER_AGENT = "Mozilla/5.0 (nhl_analytics portfolio project; personal use)"
POSITIONS = {"C", "L", "R", "D", "LW", "RW", "F"}
# official header -> boxscore column
HEADERS = {
    "G": "goals",
    "A": "assists",
    "+/-": "plus_minus",
    "PIM": "pim",
    "S": "sog",
    "HT": "hits",
    "HIT": "hits",
    "GV": "giveaways",
    "TK": "takeaways",
    "BS": "blocked_shots",
    "BKS": "blocked_shots",
    "TOI": "toi_seconds",
}
BOX_COLUMNS = (
    ["game_id", "team_id", "home_or_away", "player_group", "sweater_number", "player_id"]
    + sorted(set(HEADERS.values()) - {"toi_seconds"})
    + ["toi_seconds"]
)


class RowCollector(HTMLParser):
    """Collects the cell texts of every table row that has no table inside it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "table" and self.stack:
            self.stack[-1]["nested"] = True
        elif tag == "tr":
            self.stack.append({"cells": [], "buffer": None, "nested": False})
        elif tag in ("td", "th") and self.stack:
            self.stack[-1]["buffer"] = []

    def handle_data(self, data):
        if self.stack and self.stack[-1]["buffer"] is not None:
            self.stack[-1]["buffer"].append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.stack and self.stack[-1]["buffer"] is not None:
            frame = self.stack[-1]
            frame["cells"].append(" ".join("".join(frame["buffer"]).replace("\xa0", " ").split()))
            frame["buffer"] = None
        elif tag == "tr" and self.stack:
            frame = self.stack.pop()
            if not frame["nested"]:
                self.rows.append(frame["cells"])


def parse_rows(html):
    collector = RowCollector()
    collector.feed(html)
    return collector.rows


def to_number(text):
    """'+1' -> 1, '-2' -> -2, '12:34' -> 754 seconds, '' or anything else -> None."""
    text = text.strip()
    if ":" in text:
        minutes, _, seconds = text.partition(":")
        if minutes.isdigit() and seconds.isdigit():
            return int(minutes) * 60 + int(seconds)
        return None
    try:
        return int(text.replace("+", ""))
    except ValueError:
        return None


def full_header(header):
    """The Event Summary header has the team name over #, POS and NAME, and a second row under
    TOI (TOT, SHF, AVG, PP, SH, EV). Spell both out so the header lines up with a player row."""
    if not header or header[0] in ("#", ""):
        return list(header)
    names = ["#", "POS", "NAME"] + header[1:]
    if "TOI" in names:
        at = names.index("TOI")
        names = names[:at] + ["TOI", "SHF", "AVG", "PP", "SH", "EV"] + names[at + 1 :]
    return names


def skater_tables(rows):
    """Split the rows into skater tables: [(header, [player rows])], one per header with '+/-'.

    A player row has a jersey number first and a position second.
    """
    tables = []
    for cells in rows:
        if "+/-" in cells:
            tables.append((cells, []))
        elif tables and len(cells) > 2 and cells[0].isdigit() and cells[1] in POSITIONS:
            tables[-1][1].append(cells)
    return tables


def read_official(html):
    """{(side, jersey): {boxscore column: value}} for skaters, plus a list of problems.

    The first skater table is taken as the away team, the second as the home team (the
    order the NHL's report uses), which the printed output lets you check.
    """
    problems = []
    tables = skater_tables(parse_rows(html))
    if len(tables) != 2:
        problems.append(f"expected 2 skater tables, found {len(tables)}")
    players = {}
    used = {}
    for (raw_header, player_rows), side in zip(tables, ("away", "home")):
        header = full_header(raw_header)
        columns = {}
        for index, name in enumerate(header):
            if name in HEADERS and HEADERS[name] not in columns.values():
                columns[index] = HEADERS[name]
        used[side] = {header[i]: column for i, column in columns.items()}
        for cells in player_rows:
            if len(cells) != len(header):
                problems.append(f"{side} row has {len(cells)} cells, header has {len(header)}: {cells[:4]}")
                continue
            # the page leaves a zero blank; a blank time on ice is left as unknown
            values = {
                column: 0 if cells[i] == "" and column != "toi_seconds" else to_number(cells[i])
                for i, column in columns.items()
            }
            players[(side, int(cells[0]))] = values
    return players, used, problems


def fetch(game_id, cache_dir, report):
    season, number = divmod(game_id, 1_000_000)
    path = cache_dir / f"{report}{game_id}.HTM"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    url = URL.format(season=season, next_season=season + 1, report=report, number=number)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    time.sleep(1)
    return html


def compare_game(game_id, official, box_players):
    """Counters of (column) -> compared / same, and a list of differences."""
    compared, same, differences, unmatched = Counter(), Counter(), [], []
    for (side, jersey), values in official.items():
        ours = box_players.get((side, jersey))
        if ours is None:
            unmatched.append(f"official {side} #{jersey} not in our boxscore")
            continue
        for column, official_value in values.items():
            if official_value is None or ours.get(column) is None:
                continue
            compared[column] += 1
            if official_value == ours[column]:
                same[column] += 1
            else:
                differences.append(
                    {
                        "game_id": game_id,
                        "side": side,
                        "jersey": jersey,
                        "player_id": ours["player_id"],
                        "column": column,
                        "official": official_value,
                        "ours": ours[column],
                    }
                )
    for key in box_players:
        if key not in official:
            unmatched.append(f"our boxscore {key[0]} #{key[1]} not in the official report")
    return compared, same, differences, unmatched


def main():
    parser = argparse.ArgumentParser(description="Compare our boxscore with the official game summaries.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--games", type=int, default=20, help="how many random games to compare")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--report", default="ES", help="ES = event summary (per player), the default")
    parser.add_argument("--show", action="store_true", help="print the header and first player row of each page")
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--log-dir", type=Path, default=LOG_DIR)
    args = parser.parse_args()

    box = pq.read_table(
        args.staging_root / f"season={args.season}" / "boxscore_players.parquet",
        columns=[
            c
            for c in BOX_COLUMNS
            if c in pq.read_schema(args.staging_root / f"season={args.season}" / "boxscore_players.parquet").names
        ],
    ).to_pylist()
    by_game = {}
    for row in box:
        if row["player_group"] == "goalies" or row.get("sweater_number") is None:
            continue
        by_game.setdefault(row["game_id"], {})[(row["home_or_away"], int(row["sweater_number"]))] = row
    regular = sorted(g for g in by_game if str(g)[4:6] == "02")
    sample = random.Random(args.seed).sample(regular, min(args.games, len(regular)))

    compared, same, differences, notes = Counter(), Counter(), [], []
    games_done = 0
    for game_id in sample:
        try:
            html = fetch(game_id, args.cache_dir, args.report)
        except (urllib.error.URLError, TimeoutError) as error:
            notes.append(f"{game_id}: could not download ({error})")
            continue
        official, used, problems = read_official(html)
        notes.extend(f"{game_id}: {p}" for p in problems)
        if args.show:
            print(f"\n{game_id}: columns used {used}")
            for key in list(official)[:2]:
                print(f"  {key}: {official[key]}")
        if not official:
            continue
        games_done += 1
        c, s, d, u = compare_game(game_id, official, by_game[game_id])
        compared.update(c)
        same.update(s)
        differences.extend(d)
        notes.extend(f"{game_id}: {x}" for x in u)

    print(f"\nGames compared: {games_done} of {len(sample)} sampled (season {args.season})")
    for column in sorted(compared):
        print(f"  {column:14s} {same[column]:6d} of {compared[column]:6d} identical")
    missing = sorted(set(HEADERS.values()) - set(compared))
    if missing:
        print(f"  not compared (no matching column on the official page): {', '.join(missing)}")
    print(f"Differences: {len(differences)}; other notes: {len(notes)}")
    for item in differences[:15]:
        print("  ", item)
    for note in notes[:15]:
        print("  ", note)

    args.log_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "season": args.season,
        "games": sample,
        "compared": dict(compared),
        "identical": dict(same),
        "differences": differences,
        "notes": notes,
    }
    (args.log_dir / "compare_boxscore_to_nhl.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
