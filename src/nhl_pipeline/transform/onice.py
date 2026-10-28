"""Phase 3 logic: which players were on the ice for each event.

Everything here is plain Python on dicts and lists. Nothing reads files or
touches the network, so it is easy to test.

Inputs (rows from the staging tables):
    shifts   game_id, player_id, team_id, period, start_game_seconds, end_game_seconds
    events   game_id, event_id, sort_order, period, period_type, game_seconds,
             event_type, situation_code, event_owner_team_id

Method:
  1. Clean the shifts: drop exact duplicate rows, mark goalies, and flag shifts
     that overlap another shift by the same player with different times.
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

RULE_START_INCLUSIVE = "A"  # shift covers  start <= t <  end
RULE_END_INCLUSIVE = "B"  # shift covers  start <  t <= end


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


def clean_shifts(shift_rows, goalie_ids):
    """Remove exact duplicates, mark goalies, and flag conflicting shifts.

    Two rows are exact duplicates if player, period, start and end are the same
    (the NHL gives them different ids and shift numbers). Shifts by the same
    player in the same period that overlap without being identical are both
    kept and marked has_conflict, because we cannot tell which one is right.
    Rows with a missing start or end are dropped.
    """
    seen = set()
    shifts = []
    for row in shift_rows:
        start, end = row["start_game_seconds"], row["end_game_seconds"]
        if start is None or end is None:
            continue
        key = (row["player_id"], row["period"], start, end)
        if key in seen:
            continue
        seen.add(key)
        shifts.append(
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

    groups = {}
    for shift in shifts:
        groups.setdefault((shift["player_id"], shift["period"]), []).append(shift)
    for group in groups.values():
        group.sort(key=lambda s: (s["start"], s["end"]))
        for i, first in enumerate(group):
            for second in group[i + 1 :]:
                if second["start"] >= first["end"]:
                    break
                first["has_conflict"] = True
                second["has_conflict"] = True
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