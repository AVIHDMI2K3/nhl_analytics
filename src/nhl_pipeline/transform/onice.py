"""Phase 3 logic: which players were on the ice for each event.

Everything here is plain Python on dicts and lists. Nothing reads files or
touches the network, so it is easy to test.

Inputs (rows from the staging tables):
    shifts   game_id, player_id, team_id, period, shift_number, shift_id,
             start_game_seconds, end_game_seconds
    events   game_id, event_id, sort_order, period, period_type, game_seconds,
             event_type, situation_code, event_owner_team_id

Method:
  1. Clean the shifts: drop duplicate and overlapping rows (see clean_shifts), mark
     goalies, flag the shifts that were ambiguous, and fill goalie gaps from dropped
     period-long goalie rows (see fill_goalie_gaps).
  2. For every event, find the shifts that are active at the event's second.
     Whether the first and last second of a shift count depends on the event
     type (see END_INCLUSIVE_EVENT_TYPES). The rule was chosen by comparing the
     resulting skater counts with situationCode on 2023-24, and it held on
     2024-25 and 2025-26.
  3. Compare the on-ice counts with the four digits of situationCode and keep
     the result as a flag instead of hiding disagreements.

situationCode digit order (confirmed against the shift chart):
    [away goalie][away skaters][home skaters][home goalie]
"""

# Events where play stops: a shift that ends at the event's second still counts,
# and a shift that starts at that second does not.
END_INCLUSIVE_EVENT_TYPES = frozenset(
    {"goal", "penalty", "delayed-penalty", "period-end", "game-end"}
)

NO_NUMBER = 10**9  # sorts shift rows without a shift number or id last

RULE_START_INCLUSIVE = "A"  # shift covers  start <= t <  end
RULE_END_INCLUSIVE = "B"  # shift covers  start <  t <= end

REGULATION_PERIOD_SECONDS = 1200
MIN_PERIOD_LONG_SECONDS = 300  # the shortest period (regular-season overtime) is 5 minutes


def rule_for(event_type):
    """Boundary rule for an event type: B for events that stop play, A otherwise."""
    if event_type in END_INCLUSIVE_EVENT_TYPES:
        return RULE_END_INCLUSIVE
    return RULE_START_INCLUSIVE


def parse_situation_code(code):
    """'1551' -> goalie and skater counts for each team, or None if not four digits."""
    if not isinstance(code, str) or len(code) != 4 or not code.isdigit():
        return None
    digits = [int(char) for char in code]
    return {
        "away_goalie": digits[0],
        "away_skaters": digits[1],
        "home_skaters": digits[2],
        "home_goalie": digits[3],
    }


def overlap(start, end, other_start, other_end):
    """True if two shifts overlap. Shifts that only touch (one ends as the next starts) do not."""
    if start == other_start and end == other_end:
        return True
    return start < other_end and other_start < end


def shifts_of_game_teams(shift_rows, game):
    """Keep only shifts by the game's home or away team.

    The NHL's shift chart for game 2025020565 (NJD-BUF) also holds the shifts of another
    game (SJS-VGK). Those players are not in this game, so their rows are removed.
    """
    teams = {game["home_team_id"], game["away_team_id"]}
    return [row for row in shift_rows if row["team_id"] in teams]


def is_period_long(row):
    """A shift row that starts when its period starts and lasts at least as long as the shortest period.

    The NHL's goalie rows are sometimes a placeholder for a whole period (2400-3600, or
    3600-3900 in overtime) next to shorter rows for the same goalie.
    """
    period_start = REGULATION_PERIOD_SECONDS * (row["period"] - 1)
    return row["start_game_seconds"] == period_start and row["end_game_seconds"] - period_start >= MIN_PERIOD_LONG_SECONDS


def uncovered_parts(start, end, intervals):
    """The parts of [start, end) that no interval in `intervals` (pairs of start, end) covers, as pairs."""
    parts = []
    position = start
    for interval_start, interval_end in sorted(intervals):
        if interval_end <= position:
            continue
        if interval_start >= end:
            break
        if interval_start > position:
            parts.append((position, interval_start))
        position = max(position, interval_end)
        if position >= end:
            break
    if position < end:
        parts.append((position, end))
    return parts


def fill_goalie_gaps(shifts, dropped_rows):
    """Add goalie time from dropped period-long goalie rows, where no kept goalie row of the team covers it.

    Cleaning drops a whole-period goalie row when it overlaps a shorter row of the same goalie.
    Sometimes the shorter row ends early and the whole-period row is the only record of him in
    net afterwards, so the play-by-play names a goalie whose shift is gone (13 shots in 4 games in
    2025-26). Only the stretches that no kept goalie row of that team covers are added, and they are
    marked has_conflict. `dropped_rows` are raw shift rows; returns the added shifts.
    """
    added = []
    for row in dropped_rows:
        covered = [
            (s["start"], s["end"]) for s in shifts + added
            if s["is_goalie"] and s["team_id"] == row["team_id"] and s["period"] == row["period"]
        ]
        for start, end in uncovered_parts(row["start_game_seconds"], row["end_game_seconds"], covered):
            added.append(
                {
                    "game_id": row["game_id"],
                    "player_id": row["player_id"],
                    "team_id": row["team_id"],
                    "period": row["period"],
                    "start": start,
                    "end": end,
                    "is_goalie": True,
                    "has_conflict": True,
                }
            )
    return added


def clean_shifts(shift_rows, goalie_ids):
    """Drop duplicate and overlapping shift rows, mark goalies, and flag ambiguous shifts.

    A player cannot be on the ice twice at once, and the NHL's shift data has extra
    rows that say so: exact copies, and rows that overlap a real shift. For each
    player in each period the rows are taken in shift-number order (then shift id) and
    a row is dropped if it overlaps one already kept. On the 2023-24 season this gets
    87% of skaters to within 2 seconds of the NHL's own time-on-ice totals, against
    73% when only exact copies are removed.

    A kept shift that overlapped a dropped row that was not an exact copy is marked
    has_conflict, because the data was ambiguous there. Rows with a missing start or
    end are dropped. A dropped goalie row that lasts a whole period fills any stretch
    of its period that no kept goalie row of the team covers (see fill_goalie_gaps).
    """
    groups = {}
    for row in shift_rows:
        if row["start_game_seconds"] is None or row["end_game_seconds"] is None:
            continue
        groups.setdefault((row["player_id"], row["period"]), []).append(row)

    shifts = []
    dropped_period_long = []
    for rows in groups.values():
        rows.sort(
            key=lambda r: (
                NO_NUMBER if r.get("shift_number") is None else r["shift_number"],
                NO_NUMBER if r.get("shift_id") is None else r["shift_id"],
                r["start_game_seconds"],
                r["end_game_seconds"],
            )
        )
        kept = []
        for row in rows:
            start, end = row["start_game_seconds"], row["end_game_seconds"]
            overlapping = [s for s in kept if overlap(start, end, s["start"], s["end"])]
            if overlapping:
                for shift in overlapping:
                    if (shift["start"], shift["end"]) != (start, end):
                        shift["has_conflict"] = True
                if (
                    row["player_id"] in goalie_ids
                    and is_period_long(row)
                    and all((s["start"], s["end"]) != (start, end) for s in overlapping)
                ):
                    dropped_period_long.append(row)
                continue
            kept.append(
                {
                    "game_id": row["game_id"],
                    "player_id": row["player_id"],
                    "team_id": row["team_id"],
                    "period": row["period"],
                    "start": start,
                    "end": end,
                    "is_goalie": row["player_id"] in goalie_ids,
                    "has_conflict": False,
                }
            )
        shifts.extend(kept)
    dropped_period_long.sort(key=lambda r: (r["period"], r["team_id"], r["player_id"]))
    shifts.extend(fill_goalie_gaps(shifts, dropped_period_long))
    shifts.sort(key=lambda s: (s["start"], s["end"], s["player_id"]))
    return shifts


def active_shifts(shifts, times, rule):
    """For each second in `times`, the shifts that are active under `rule`.

    Returns {second: [shift, ...]}. A sweep over the shifts sorted by start, so
    the cost grows with the number of shifts plus the number of events.
    """
    ordered = sorted(shifts, key=lambda s: s["start"])
    result = {}
    active = []
    next_shift = 0
    for t in sorted(set(times)):
        while next_shift < len(ordered):
            start = ordered[next_shift]["start"]
            started = start <= t if rule == RULE_START_INCLUSIVE else start < t
            if not started:
                break
            active.append(ordered[next_shift])
            next_shift += 1
        if rule == RULE_START_INCLUSIVE:
            active = [s for s in active if t < s["end"]]
        else:
            active = [s for s in active if t <= s["end"]]
        result[t] = list(active)
    return result


def on_ice_row(game, event, rule, active):
    """One output row: the players on the ice for one event, and the situationCode check."""
    sides = {"home": ([], []), "away": ([], [])}  # side -> (skaters, goalies)
    uses_conflict = False
    for shift in active:
        if shift["team_id"] == game["home_team_id"]:
            side = "home"
        elif shift["team_id"] == game["away_team_id"]:
            side = "away"
        else:
            continue
        skaters, goalies = sides[side]
        (goalies if shift["is_goalie"] else skaters).append(shift["player_id"])
        uses_conflict = uses_conflict or shift["has_conflict"]

    ids = {
        "home_skater_ids": sorted(set(sides["home"][0])),
        "away_skater_ids": sorted(set(sides["away"][0])),
        "home_goalie_ids": sorted(set(sides["home"][1])),
        "away_goalie_ids": sorted(set(sides["away"][1])),
    }
    counts = {
        "home_skaters": len(ids["home_skater_ids"]),
        "away_skaters": len(ids["away_skater_ids"]),
        "home_goalie": len(ids["home_goalie_ids"]),
        "away_goalie": len(ids["away_goalie_ids"]),
    }
    code = parse_situation_code(event["situation_code"])
    matches = None if code is None else all(code[key] == counts[key] for key in counts)

    return {
        "game_id": event["game_id"],
        "event_id": event["event_id"],
        "sort_order": event["sort_order"],
        "period": event["period"],
        "game_seconds": event["game_seconds"],
        "event_type": event["event_type"],
        "event_owner_team_id": event["event_owner_team_id"],
        "rule": rule,
        "situation_code": event["situation_code"],
        "away_goalie_code": code["away_goalie"] if code else None,
        "away_skaters_code": code["away_skaters"] if code else None,
        "home_skaters_code": code["home_skaters"] if code else None,
        "home_goalie_code": code["home_goalie"] if code else None,
        "home_skaters_on_ice": counts["home_skaters"],
        "away_skaters_on_ice": counts["away_skaters"],
        "home_goalies_on_ice": counts["home_goalie"],
        "away_goalies_on_ice": counts["away_goalie"],
        "matches_situation": matches,
        "uses_conflicting_shift": uses_conflict,
        **ids,
    }


def build_event_on_ice(game, events, shifts):
    """On-ice rows for every event of one game, in the order the NHL lists them.

    Shootout events and events without a game clock are skipped (a shootout has
    no shifts).
    """
    by_rule = {RULE_START_INCLUSIVE: [], RULE_END_INCLUSIVE: []}
    for event in events:
        if event["period_type"] == "SO" or event["game_seconds"] is None:
            continue
        by_rule[rule_for(event["event_type"])].append(event)

    rows = []
    for rule, rule_events in by_rule.items():
        if not rule_events:
            continue
        active = active_shifts(shifts, [e["game_seconds"] for e in rule_events], rule)
        for event in rule_events:
            rows.append(on_ice_row(game, event, rule, active[event["game_seconds"]]))
    rows.sort(key=lambda r: (r["sort_order"] is None, r["sort_order"], r["event_id"]))
    return rows


def real_skaters(skaters, goalie):
    """Skaters a team really has: one fewer when its goalie is pulled for an extra attacker."""
    return skaters - 1 if goalie == 0 else skaters


def game_plus_minus(game, rows):
    """Plus/minus per skater for one game, from the goal rows of build_event_on_ice.

    Follows the NHL rule: a goal counts +1 for the scoring team's skaters on the
    ice and -1 for the other team's, except power-play goals and penalty-shot
    goals, which count for nobody. A goal is treated as a power-play goal when the
    scoring team has more skaters than the other team, not counting an extra
    attacker: a team with its goalie pulled counts one skater fewer. (So 0641,
    away 6 skaters and no goalie against 4, is a power play for the away team,
    but 0651 is even strength.) A penalty shot shows up in situationCode as one
    skater and no goalie for the shooting team against no skaters and a goalie
    (1010 or 0101). Returns {player_id: value}.
    """
    totals = {}
    for row in rows:
        if row["event_type"] != "goal":
            continue
        owner = row["event_owner_team_id"]
        if owner == game["home_team_id"]:
            side, other = "home", "away"
        elif owner == game["away_team_id"]:
            side, other = "away", "home"
        else:
            continue
        own_skaters = row[f"{side}_skaters_code"]
        other_skaters = row[f"{other}_skaters_code"]
        own_goalie = row[f"{side}_goalie_code"]
        other_goalie = row[f"{other}_goalie_code"]
        if own_skaters == 1 and own_goalie == 0 and other_skaters == 0 and other_goalie == 1:
            continue  # penalty shot
        if own_skaters is not None and real_skaters(own_skaters, own_goalie) > real_skaters(
            other_skaters, other_goalie
        ):
            continue  # power play
        for player_id in row[f"{side}_skater_ids"]:
            totals[player_id] = totals.get(player_id, 0) + 1
        for player_id in row[f"{other}_skater_ids"]:
            totals[player_id] = totals.get(player_id, 0) - 1
    return totals