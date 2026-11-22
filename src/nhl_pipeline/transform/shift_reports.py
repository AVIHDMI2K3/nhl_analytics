"""Parse the NHL's HTML time-on-ice reports into shift rows (Phase 5, for games the shift-chart API leaves empty).

Plain Python, no files or network. A report (https://www.nhl.com/scores/htmlreports/<season>/TH<game>.HTM for the home
team, TV for the visitor) holds one table per player, headed '3 PELECH, ADAM' (jersey number and name), with a row per
shift: shift number, period, 'start elapsed / game clock', 'end elapsed / game clock', duration, event. Times are
converted to game seconds the same way as the staging shifts: period 1-3 start at (period - 1) * 1200, a 5-minute
overtime period starts at 3600. The report has no player ids, so players are matched by jersey number through the
game's boxscore (see shift_rows).
"""

import re

PERIOD_SECONDS = 1200
OVERTIME_START = 3 * PERIOD_SECONDS
HEADING = re.compile(r'<td[^>]*class="playerHeading[^"]*"[^>]*>(.*?)</td>', re.S)
TEAM = re.compile(r'<td[^>]*class="teamHeading[^"]*"[^>]*>(.*?)</td>', re.S)
ROW = re.compile(r'<tr[^>]*class="\s*(?:oddColor|evenColor)\s*"[^>]*>(.*?)</tr>', re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
ELAPSED = re.compile(r"^(\d{1,2}):(\d{2})\s*/\s*\d{1,2}:\d{2}$")
PLAYER = re.compile(r"^(\d+)\s+(.*)$")


def clean(text):
    """Cell text without tags, entities for a space, or surrounding whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text).replace("&nbsp;", " ")).strip()


def period_start(period):
    """Game second at which a period starts: 1, 2, 3 -> 0, 1200, 2400; overtime (4 or 'OT') -> 3600."""
    return (period - 1) * PERIOD_SECONDS if period <= 3 else OVERTIME_START + (period - 4) * 300


def parse_period(text):
    """1, 2, 3 for those periods, 4 for 'OT'; None for anything else (a shootout has no shifts)."""
    text = text.strip().upper()
    if text.isdigit():
        return int(text)
    return 4 if text == "OT" else None


def parse_report(html):
    """{'team': name, 'players': [{'number', 'name', 'shifts': [{'shift_number', 'period', 'start', 'end'}]}]}."""
    team = TEAM.search(html)
    players = []
    events = sorted(
        [(m.start(), "player", m) for m in HEADING.finditer(html)]
        + [(m.start(), "row", m) for m in ROW.finditer(html)],
        key=lambda item: item[0],
    )
    for _, kind, match in events:
        if kind == "player":
            found = PLAYER.match(clean(match.group(1)))
            if found:
                players.append({"number": int(found.group(1)), "name": found.group(2), "shifts": []})
            else:
                players.append(None)  # a heading we cannot read: its shifts are dropped
            continue
        if not players or players[-1] is None:
            continue
        cells = [clean(cell) for cell in CELL.findall(match.group(1))]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        period = parse_period(cells[1])
        start, end = ELAPSED.match(cells[2]), ELAPSED.match(cells[3])
        if period is None or not start or not end:
            continue
        base = period_start(period)
        players[-1]["shifts"].append(
            {
                "shift_number": int(cells[0]),
                "period": period,
                "start": base + int(start.group(1)) * 60 + int(start.group(2)),
                "end": base + int(end.group(1)) * 60 + int(end.group(2)),
            }
        )
    return {"team": clean(team.group(1)) if team else None, "players": [p for p in players if p]}


def shift_rows(game_id, team_id, parsed, id_by_number):
    """(staging-style shift rows, [(number, name) of players with no id]) for one parsed report.

    id_by_number maps a jersey number to the player id for this team in this game (from the boxscore). Rows have the
    staging columns game_id, player_id, team_id, period, shift_number, shift_id (None, the report has none),
    start_game_seconds, end_game_seconds, plus player_name ('PELECH, ADAM') for to_staging_row."""
    rows, unmatched = [], []
    for player in parsed["players"]:
        player_id = id_by_number.get(player["number"])
        if player_id is None:
            unmatched.append((player["number"], player["name"]))
            continue
        for shift in player["shifts"]:
            rows.append(
                {
                    "game_id": game_id,
                    "player_id": player_id,
                    "player_name": player["name"],
                    "team_id": team_id,
                    "period": shift["period"],
                    "shift_number": shift["shift_number"],
                    "shift_id": None,
                    "start_game_seconds": shift["start"],
                    "end_game_seconds": shift["end"],
                }
            )
    return rows, unmatched


def toi_differences(rows, toi_by_player, tolerance=2):
    """[(player_id, seconds in the shifts, seconds in the boxscore)] for players whose two totals differ by more than
    `tolerance` seconds. Players in the boxscore with time on ice but no shifts are included; players with neither are
    not. This is an independent check of a report: the boxscore time on ice does not come from the same shifts."""
    from_shifts = {}
    for row in rows:
        from_shifts[row["player_id"]] = (
            from_shifts.get(row["player_id"], 0) + row["end_game_seconds"] - row["start_game_seconds"]
        )
    differing = []
    for player_id in sorted(set(from_shifts) | set(toi_by_player)):
        mine, official = from_shifts.get(player_id, 0), toi_by_player.get(player_id) or 0
        if abs(mine - official) > tolerance:
            differing.append((player_id, mine, official))
    return differing


def to_staging_row(row, team_abbrev, season):
    """A shift row of shift_rows as a row of the staging shifts table (columns of shifts.parquet).

    The report has no shift id and no separate first and last name, so shift_id is empty and the 'LAST, FIRST' name is
    split and written in title case."""
    last, _, first = (row.get("player_name") or "").partition(",")
    return {
        "game_id": row["game_id"],
        "shift_id": None,
        "player_id": row["player_id"],
        "first_name": first.strip().title() or None,
        "last_name": last.strip().title() or None,
        "team_id": row["team_id"],
        "team": team_abbrev,
        "period": row["period"],
        "shift_number": row["shift_number"],
        "start_seconds_in_period": row["start_game_seconds"] - period_start(row["period"]),
        "end_seconds_in_period": row["end_game_seconds"] - period_start(row["period"]),
        "start_game_seconds": row["start_game_seconds"],
        "end_game_seconds": row["end_game_seconds"],
        "duration_seconds": row["end_game_seconds"] - row["start_game_seconds"],
        "season": season,
    }
