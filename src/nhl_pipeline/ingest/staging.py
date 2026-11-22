"""Phase 2 parsing: turn raw NHL responses into flat rows for the staging tables.

Every function here takes already-loaded JSON (dicts and lists) and returns
plain Python rows (lists of dicts). Nothing here reads files, writes files or
touches the network, so it is easy to test.

Tables:
    games             one row per game (from the weekly schedule)
    players           one row per player per game (from play-by-play rosterSpots)
    events            one row per play-by-play event
    shifts            one row per shift (shift chart rows with typeCode 517)
    boxscore_players  one row per player per game (the official boxscore numbers)

Fields that were not confirmed against real responses are read with .get(), so
a missing field becomes null rather than an error. Anything on an event that
has no column of its own is kept in `details_json`, so no information is lost.
"""

import json
import re

SHIFT_TYPE_CODE = 517  # 505 is a goal marker row in the shift chart
GOAL_MARKER_TYPE_CODE = 505

# Regular season clock: three 20-minute periods, a 5-minute overtime (period 4),
# then a shootout (period 5) that has no running clock.
REGULATION_PERIOD_SECONDS = 1200
OVERTIME_PERIOD_SECONDS = 300


# ---- small helpers ----------------------------------------------------------


def clock_to_seconds(text):
    """'11:39' -> 699. Returns None for a missing or malformed value."""
    if not text or not isinstance(text, str) or ":" not in text:
        return None
    minutes, _, seconds = text.partition(":")
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return None


def period_start_seconds(period):
    """Game seconds at the start of a period (regular-season clock)."""
    if period is None:
        return None
    if period <= 3:
        return (period - 1) * REGULATION_PERIOD_SECONDS
    return 3 * REGULATION_PERIOD_SECONDS + (period - 4) * OVERTIME_PERIOD_SECONDS


def snake_case(name):
    """'powerPlayGoals' -> 'power_play_goals', 'playerId' -> 'player_id'."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def localized(value):
    """{'default': 'Ottawa', 'fr': ...} -> 'Ottawa'; other values pass through."""
    if isinstance(value, dict):
        return value.get("default")
    return value


def _nested(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


# ---- games ------------------------------------------------------------------


def parse_schedule_week(schedule):
    """Rows for every game in one weekly schedule response."""
    rows = []
    for day in schedule.get("gameWeek", []):
        for game in day.get("games", []):
            rows.append(
                {
                    "game_id": int(game["id"]),
                    "game_type": game.get("gameType"),
                    "game_date": day.get("date"),
                    "start_time_utc": game.get("startTimeUTC"),
                    "game_state": game.get("gameState"),
                    "game_schedule_state": game.get("gameScheduleState"),
                    "home_team_id": _nested(game, "homeTeam", "id"),
                    "home_team": _nested(game, "homeTeam", "abbrev"),
                    "home_score": _nested(game, "homeTeam", "score"),
                    "away_team_id": _nested(game, "awayTeam", "id"),
                    "away_team": _nested(game, "awayTeam", "abbrev"),
                    "away_score": _nested(game, "awayTeam", "score"),
                    "last_period_number": _nested(game, "periodDescriptor", "number"),
                    "last_period_type": _nested(game, "gameOutcome", "lastPeriodType"),
                }
            )
    return rows


def merge_games(weekly_rows):
    """One row per game. A game seen in two weekly responses keeps the later one."""
    by_id = {}
    for row in weekly_rows:
        by_id[row["game_id"]] = row
    return [by_id[game_id] for game_id in sorted(by_id)]


# ---- players ----------------------------------------------------------------


def parse_roster(game_id, pbp):
    rows = []
    for spot in pbp.get("rosterSpots", []):
        rows.append(
            {
                "game_id": game_id,
                "team_id": spot.get("teamId"),
                "player_id": spot.get("playerId"),
                "first_name": localized(spot.get("firstName")),
                "last_name": localized(spot.get("lastName")),
                "sweater_number": spot.get("sweaterNumber"),
                "position_code": spot.get("positionCode"),
            }
        )
    return rows


# ---- events -----------------------------------------------------------------

# Columns taken from each event's `details`. Names on the left are the NHL's
# field names; the right-hand names are the column names we use. Any other
# detail field goes into details_json.
EVENT_DETAIL_COLUMNS = {
    "eventOwnerTeamId": "event_owner_team_id",
    "xCoord": "x_coord",
    "yCoord": "y_coord",
    "zoneCode": "zone_code",
    "shotType": "shot_type",
    "reason": "reason",
    "secondaryReason": "secondary_reason",
    "shootingPlayerId": "shooting_player_id",
    "scoringPlayerId": "scoring_player_id",
    "assist1PlayerId": "assist1_player_id",
    "assist2PlayerId": "assist2_player_id",
    "goalieInNetId": "goalie_in_net_id",
    "blockingPlayerId": "blocking_player_id",
    "hittingPlayerId": "hitting_player_id",
    "hitteePlayerId": "hittee_player_id",
    "winningPlayerId": "winning_player_id",
    "losingPlayerId": "losing_player_id",
    "playerId": "player_id",
    "committedByPlayerId": "committed_by_player_id",
    "drawnByPlayerId": "drawn_by_player_id",
    "servedByPlayerId": "served_by_player_id",
    "descKey": "penalty_desc_key",
    "typeCode": "penalty_type_code",
    "duration": "penalty_minutes",
    "awayScore": "away_score",
    "homeScore": "home_score",
    "awaySOG": "away_sog",
    "homeSOG": "home_sog",
}


def parse_events(game_id, pbp):
    """One row per play-by-play event, in the order the NHL lists them."""
    rows = []
    for play in pbp.get("plays", []):
        period_info = play.get("periodDescriptor") or {}
        period = period_info.get("number")
        elapsed = clock_to_seconds(play.get("timeInPeriod"))
        start = period_start_seconds(period)
        row = {
            "game_id": game_id,
            "event_id": play.get("eventId"),
            "sort_order": play.get("sortOrder"),
            "period": period,
            "period_type": period_info.get("periodType"),
            "time_in_period": play.get("timeInPeriod"),
            "seconds_in_period": elapsed,
            "game_seconds": (start + elapsed) if start is not None and elapsed is not None else None,
            "seconds_remaining_in_period": clock_to_seconds(play.get("timeRemaining")),
            "event_type": play.get("typeDescKey"),
            "event_type_code": play.get("typeCode"),
            "situation_code": play.get("situationCode"),
            "home_defending_side": play.get("homeTeamDefendingSide"),
        }
        for column in EVENT_DETAIL_COLUMNS.values():
            row[column] = None
        details = play.get("details") or {}
        extra = {}
        for key, value in details.items():
            column = EVENT_DETAIL_COLUMNS.get(key)
            if column is not None and not isinstance(value, (dict, list)):
                row[column] = value
            else:
                extra[key] = value
        row["details_json"] = json.dumps(extra, sort_keys=True) if extra else None
        rows.append(row)
    return rows


# ---- shifts -----------------------------------------------------------------


def parse_shifts(game_id, shiftchart):
    """One row per shift. Goal-marker rows (typeCode 505) are dropped."""
    rows = []
    for item in shiftchart.get("data", []):
        if item.get("typeCode") != SHIFT_TYPE_CODE:
            continue
        period = item.get("period")
        start = clock_to_seconds(item.get("startTime"))
        end = clock_to_seconds(item.get("endTime"))
        offset = period_start_seconds(period)
        rows.append(
            {
                "game_id": game_id,
                "shift_id": item.get("id"),
                "player_id": item.get("playerId"),
                "first_name": item.get("firstName"),
                "last_name": item.get("lastName"),
                "team_id": item.get("teamId"),
                "team": item.get("teamAbbrev"),
                "period": period,
                "shift_number": item.get("shiftNumber"),
                "start_seconds_in_period": start,
                "end_seconds_in_period": end,
                "start_game_seconds": offset + start if offset is not None and start is not None else None,
                "end_game_seconds": offset + end if offset is not None and end is not None else None,
                "duration_seconds": clock_to_seconds(item.get("duration")),
            }
        )
    return rows


# ---- boxscore ---------------------------------------------------------------


def _scalar(value):
    """Keep numbers, strings and booleans; unwrap {'default': x}; drop the rest."""
    value = localized(value)
    if isinstance(value, (dict, list)):
        return None
    return value


def parse_boxscore_players(game_id, boxscore):
    """One row per player. Columns are whatever scalar fields the NHL provides.

    Column names are converted to snake_case (playerId -> player_id). Skaters and
    goalies carry different fields, so a column that does not apply to a player
    is null. `toi_seconds` is added when the player has a `toi`.
    """
    rows = []
    by_team = boxscore.get("playerByGameStats") or {}
    for side, team_key in (("home", "homeTeam"), ("away", "awayTeam")):
        team_id = _nested(boxscore, team_key, "id")
        groups = by_team.get(team_key) or {}
        for group, players in groups.items():
            if not isinstance(players, list):
                continue
            for player in players:
                row = {
                    "game_id": game_id,
                    "team_id": team_id,
                    "home_or_away": side,
                    "player_group": group,
                }
                for key, value in player.items():
                    row[snake_case(key)] = _scalar(value)
                if isinstance(row.get("toi"), str):
                    row["toi_seconds"] = clock_to_seconds(row["toi"])
                rows.append(row)
    return rows


# ---- per-game checks --------------------------------------------------------


def check_goals(game, event_rows):
    """Compare goals counted from events with the final score in the schedule.

    Shootout goals are not counted from events. In a shootout game the winning
    team's official score includes one extra goal for the shootout win.
    Returns None if the game matches, otherwise a short description.
    """
    home_goals = away_goals = 0
    for row in event_rows:
        if row["event_type"] != "goal" or row["period_type"] == "SO":
            continue
        if row["event_owner_team_id"] == game["home_team_id"]:
            home_goals += 1
        elif row["event_owner_team_id"] == game["away_team_id"]:
            away_goals += 1
    home_score, away_score = game["home_score"], game["away_score"]
    if home_score is None or away_score is None:
        return "score missing in schedule"
    if game["last_period_type"] == "SO":
        if home_score > away_score:
            home_score -= 1
        else:
            away_score -= 1
    if (home_goals, away_goals) != (home_score, away_score):
        return f"events {home_goals}-{away_goals} (home-away) vs score {home_score}-{away_score}"
    return None


def check_shifts(shift_rows):
    """Count shifts that end before they start, and overlapping shifts by one player."""
    backwards = 0
    overlaps = 0
    by_player = {}
    for row in shift_rows:
        start, end = row["start_game_seconds"], row["end_game_seconds"]
        if start is None or end is None:
            continue
        if end < start:
            backwards += 1
        by_player.setdefault((row["player_id"], row["period"]), []).append((start, end))
    for spans in by_player.values():
        spans.sort()
        for (_, prev_end), (next_start, _) in zip(spans, spans[1:]):
            if next_start < prev_end:
                overlaps += 1
    return {"backwards": backwards, "overlaps": overlaps}
