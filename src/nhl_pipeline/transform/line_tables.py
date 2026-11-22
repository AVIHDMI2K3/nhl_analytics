"""Phase 6: forward lines and defense pairs at 5v5 (pure logic, no file access).

A unit is a forward line (3 forwards) or a defense pair (2 defensemen), see lines.py. For one game this adds up,
for every unit of every team, the seconds it was on the ice at 5v5 and the shot attempts for and against while it
was. The rules are the ones of the base tables (base_tables.py), so a line's numbers add up to the same attempts the
skaters' 5v5 numbers use:
  * seconds come from the stints whose own state is 5v5 (five skaters and a goalie each side);
  * an attempt counts at 5v5 when its state (from the NHL situationCode when the row has it, else the stint's) is
    5v5, and is credited to the unit on the ice by base_tables.credited_stints;
  * a unit is the exact set of 3 forwards or 2 defensemen on the ice; a stint with a different count (for example
    4 forwards) has no line.
Season rows (season_unit_rows) sum the games and add the percentages and per-60 rates, never averaging rates.
"""

from collections import Counter, defaultdict

from base_tables import KIND_BY_ATTEMPT, KINDS, code_states, credited_stints
from lines import units_on_ice
from stints import SIDES, StintIndex, other_side, side_state

FIVE_ON_FIVE = (5, 5, 1, 1)  # skaters for, skaters against, goalies for, goalies against
UNIT_TYPES = ("line", "pair")
FORWARD_POSITIONS = {"C", "L", "R", "LW", "RW", "F"}
COUNT_COLUMNS = ["seconds"] + [f"for_{k}" for k in KINDS] + [f"against_{k}" for k in KINDS]


def is_five_on_five(state):
    """True for a (strength, skaters_for, skaters_against, goalies_for, goalies_against) state at 5v5."""
    return tuple(state[1:]) == FIVE_ON_FIVE


def units_of(skater_ids, positions):
    """[(unit type, sorted tuple of player ids)] of the line and the pair among these skaters."""
    line, pair = units_on_ice(skater_ids, positions)
    found = []
    if line is not None:
        found.append(("line", tuple(sorted(line))))
    if pair is not None:
        found.append(("pair", tuple(sorted(pair))))
    return found


def build_game_unit_rows(game, stints, attempts, positions):
    """Rows for one game: one per team and unit, with the game's 5v5 seconds and attempts for and against.

    `stints` are rows from stints.stint_rows, `attempts` shot_attempts rows (attempt_type, game_seconds, is_home,
    and optionally the situationCode counts skaters_for, skaters_against, goalie_for, goalie_against), and
    `positions` maps a player id to 'F' or 'D' for this game."""
    team_ids = {"home": game["home_team_id"], "away": game["away_team_id"]}
    totals = defaultdict(Counter)

    for stint in stints:
        for side in SIDES:
            if is_five_on_five(side_state(stint, side)):
                for unit in units_of(stint[f"{side}_skater_ids"], positions):
                    totals[(team_ids[side], *unit)]["seconds"] += stint["seconds"]

    index = StintIndex(stints)
    for attempt in attempts:
        kind = KIND_BY_ATTEMPT.get(attempt["attempt_type"])
        if kind is None:
            continue
        credited = credited_stints(index, attempt, kind)
        if credited is None:
            continue
        stint, shooting_stint, defending_stint = credited
        shooting = "home" if attempt["is_home"] else "away"
        defending = other_side(shooting)
        from_code = code_states(attempt)
        state = from_code[0] if from_code is not None else side_state(stint, shooting)
        if not is_five_on_five(state):
            continue
        for unit in units_of(shooting_stint[f"{shooting}_skater_ids"], positions):
            totals[(team_ids[shooting], *unit)][f"for_{kind}"] += 1
        for unit in units_of(defending_stint[f"{defending}_skater_ids"], positions):
            totals[(team_ids[defending], *unit)][f"against_{kind}"] += 1

    rows = []
    for (team_id, unit_type, player_ids), counts in sorted(totals.items()):
        row = {"game_id": game["game_id"], "team_id": team_id, "unit_type": unit_type, "player_ids": list(player_ids)}
        row.update({column: counts[column] for column in COUNT_COLUMNS})
        rows.append(row)
    return rows


def percent(for_count, against_count):
    """for / (for + against) as a percentage, or None when both are zero."""
    total = for_count + against_count
    return 100 * for_count / total if total else None


def per_60(count, seconds):
    return count * 3600 / seconds if seconds else None


def season_unit_rows(game_rows):
    """One row per team and unit, summed over the games: games together, seconds, attempts and the rates.

    cf/ca are Corsi (goals, shots on goal, misses, blocks), ff/fa Fenwick (no blocks), sf/sa shots on goal (with
    goals), gf/ga goals. Percentages are 0-100; sh_pct is gf / sf, sv_pct is 1 - ga / sa, and pdo is their sum
    (about 100)."""
    totals = defaultdict(Counter)
    for row in game_rows:
        key = (row["team_id"], row["unit_type"], tuple(row["player_ids"]))
        for column in COUNT_COLUMNS:
            totals[key][column] += row[column]
        if row["seconds"] > 0:
            totals[key]["games"] += 1
    rows = []
    for (team_id, unit_type, player_ids), c in sorted(totals.items()):
        goal_for, sog_for, miss_for, block_for = (c[f"for_{k}"] for k in KINDS)
        goal_against, sog_against, miss_against, block_against = (c[f"against_{k}"] for k in KINDS)
        cf, ca = goal_for + sog_for + miss_for + block_for, goal_against + sog_against + miss_against + block_against
        ff, fa = goal_for + sog_for + miss_for, goal_against + sog_against + miss_against
        sf, sa = goal_for + sog_for, goal_against + sog_against
        gf, ga = goal_for, goal_against
        sh_pct = 100 * gf / sf if sf else None
        sv_pct = 100 * (1 - ga / sa) if sa else None
        row = {
            "team_id": team_id,
            "unit_type": unit_type,
            "player_ids": list(player_ids),
            "games": c["games"],
            "seconds": c["seconds"],
            "cf": cf,
            "ca": ca,
            "ff": ff,
            "fa": fa,
            "sf": sf,
            "sa": sa,
            "gf": gf,
            "ga": ga,
            "cf_pct": percent(cf, ca),
            "ff_pct": percent(ff, fa),
            "sf_pct": percent(sf, sa),
            "gf_pct": percent(gf, ga),
            "sh_pct": sh_pct,
            "sv_pct": sv_pct,
            "pdo": sh_pct + sv_pct if sh_pct is not None and sv_pct is not None else None,
        }
        for name in ("cf", "ca", "gf", "ga"):
            row[f"{name}_per_60"] = per_60(row[name], c["seconds"])
        rows.append(row)
    return rows


def describe_units(season_rows, thresholds=(30, 60, 100)):
    """Time-together summary per unit type: {unit type: {'units', 'median', 'mean', 'p90', 'max', 'at_least': {minutes:
    number of units}, 'per_team': {minutes: average number of units per team}}}; minutes are 5v5 minutes."""
    summary = {}
    for unit_type in UNIT_TYPES:
        rows = [r for r in season_rows if r["unit_type"] == unit_type]
        minutes = sorted(r["seconds"] / 60 for r in rows)
        if not minutes:
            continue
        teams = len({r["team_id"] for r in rows})
        summary[unit_type] = {
            "units": len(minutes),
            "median": minutes[len(minutes) // 2],
            "mean": sum(minutes) / len(minutes),
            "p90": minutes[int(0.9 * (len(minutes) - 1))],
            "max": minutes[-1],
            "at_least": {t: sum(m >= t for m in minutes) for t in thresholds},
            "per_team": {t: sum(m >= t for m in minutes) / teams for t in thresholds},
        }
    return summary


def positions_by_game(box_rows):
    """{game_id: {player_id: 'F' or 'D'}} from the boxscore; goalies and unknown positions are left out."""
    positions = defaultdict(dict)
    for row in box_rows:
        position = (row.get("position") or "").upper()
        group = (row.get("player_group") or "").lower()
        if position in FORWARD_POSITIONS or group == "forwards":
            positions[row["game_id"]][row["player_id"]] = "F"
        elif position == "D" or group == "defense":
            positions[row["game_id"]][row["player_id"]] = "D"
    return positions
