"""Phase 4.2: stints (stretches with a fixed lineup) and time on ice by strength. Pure logic.

A stint is a stretch of one period in which nobody changes: the same skaters and
goalies are on the ice for both teams. Any shift start or end starts a new stint.
Stints are half-open, [start, end), in game seconds, and never cross a period.

Strength is seen from one team: "ev" (even), "pp" (more real skaters than the
opponent) or "sh" (fewer). A team whose goalie is off the ice has one fewer real
skater, because its sixth skater is an extra attacker.

Three ways to know the strength during a stint are compared against the NHL's own
even-strength, power-play and shorthanded totals (scripts/test_strength_toi.py):
  - from the skaters on the ice (shift counts), raw or goalie-adjusted
  - from the situationCode of the previous event
  - from the situationCode of the next event
"""

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict

from onice import parse_situation_code, real_skaters

SIDES = ("home", "away")
SMOOTH_SECONDS = 2  # tested on 2023 and 2025; 5 and 10 seconds are worse


def build_stints(game, shifts):
    """Stints for one game from cleaned shifts (rows as in shifts_clean).

    Stretches with nobody on the ice (intermissions) are not stints. Consecutive
    stints with the same lineup, such as where one player's shift ends as his next
    begins, are merged into one.
    """
    by_period = defaultdict(list)
    for shift in shifts:
        by_period[shift["period"]].append(shift)

    stints = []
    for period in sorted(by_period):
        changes = defaultdict(lambda: ([], []))  # time -> (shifts ending, shifts starting)
        for shift in by_period[period]:
            changes[shift["end_game_seconds"]][0].append(shift)
            changes[shift["start_game_seconds"]][1].append(shift)
        times = sorted(changes)
        active = {}
        for index, time in enumerate(times):
            ending, starting = changes[time]
            for shift in ending:
                active.pop(shift["player_id"], None)
            for shift in starting:
                active[shift["player_id"]] = shift
            if index + 1 == len(times) or not active:
                continue
            stint = lineup(game, period, time, times[index + 1], active.values())
            previous = stints[-1] if stints else None
            if previous and previous["period"] == period and previous["end"] == time and same_lineup(previous, stint):
                previous["end"] = stint["end"]
            else:
                stints.append(stint)
    return stints


def lineup(game, period, start, end, active_shifts):
    stint = {
        "game_id": game["game_id"], "period": period, "start": start, "end": end,
        "home_skater_ids": [], "away_skater_ids": [], "home_goalie_ids": [], "away_goalie_ids": [],
    }
    for shift in active_shifts:
        if shift["team_id"] == game["home_team_id"]:
            side = "home"
        elif shift["team_id"] == game["away_team_id"]:
            side = "away"
        else:
            continue
        kind = "goalie" if shift["is_goalie"] else "skater"
        stint[f"{side}_{kind}_ids"].append(shift["player_id"])
    for key in ("home_skater_ids", "away_skater_ids", "home_goalie_ids", "away_goalie_ids"):
        stint[key].sort()
    return stint


def same_lineup(a, b):
    return all(
        a[key] == b[key]
        for key in ("home_skater_ids", "away_skater_ids", "home_goalie_ids", "away_goalie_ids")
    )


def strength_label(real_for, real_against):
    if real_for == real_against:
        return "ev"
    return "pp" if real_for > real_against else "sh"


def other_side(side):
    return "away" if side == "home" else "home"


def side_state(stint, side):
    """The state of one side of a stint, as (strength, skaters_for, skaters_against,
    goalies_for, goalies_against)."""
    other = other_side(side)
    return (
        stint[f"{side}_strength"],
        len(stint[f"{side}_skater_ids"]),
        len(stint[f"{other}_skater_ids"]),
        len(stint[f"{side}_goalie_ids"]),
        len(stint[f"{other}_goalie_ids"]),
    )


def strength_from_shifts(stint, side, adjust_goalie=True):
    """Strength for `side` from the skaters on the ice. With adjust_goalie, a team
    without a goalie on the ice has one fewer real skater."""
    counts = {}
    for name in SIDES:
        skaters, goalies = len(stint[f"{name}_skater_ids"]), len(stint[f"{name}_goalie_ids"])
        counts[name] = real_skaters(skaters, goalies) if adjust_goalie else skaters
    return strength_label(counts[side], counts[other_side(side)])


def strength_from_code(code, side):
    """Strength for `side` from a situationCode string, or None if it cannot be read.
    The goalie digit is 0 for a pulled goalie."""
    parsed = parse_situation_code(code)
    if parsed is None:
        return None
    real = {
        "home": real_skaters(parsed["home_skaters"], parsed["home_goalie"]),
        "away": real_skaters(parsed["away_skaters"], parsed["away_goalie"]),
    }
    return strength_label(real[side], real[other_side(side)])


class CodeSteps:
    """The situationCode over game time, from a game's events, for lookup by time."""

    def __init__(self, events):
        usable = [
            (e["game_seconds"], e["sort_order"] if e["sort_order"] is not None else 10**9, e["situation_code"])
            for e in events
            if e["game_seconds"] is not None and e["situation_code"] is not None
            and e.get("period_type") != "SO"
        ]
        usable.sort(key=lambda row: (row[0], row[1]))
        self.times = [row[0] for row in usable]
        self.codes = [row[2] for row in usable]

    def previous(self, time):
        """Code of the last event at or before `time`."""
        index = bisect_right(self.times, time) - 1
        return self.codes[index] if index >= 0 else None

    def next(self, time):
        """Code of the first event after `time`."""
        index = bisect_right(self.times, time)
        return self.codes[index] if index < len(self.codes) else None


def seconds_by_strength(stints, label_for):
    """Seconds per (player_id, strength) for skaters. `label_for(stint, side)` gives the
    strength label for a side, or None to leave the stint out."""
    totals = Counter()
    for stint in stints:
        length = stint["end"] - stint["start"]
        for side in SIDES:
            label = label_for(stint, side)
            if label is None:
                continue
            for player_id in stint[f"{side}_skater_ids"]:
                totals[(player_id, label)] += length
    return totals


def smoothed_label_for(stints, label_for, max_seconds):
    """A label function that removes short blips in a team's strength.

    Shift data is only accurate to about a second, so a line change can leave a team
    briefly with one skater too many or too few. A stint of at most `max_seconds` whose
    strength differs from the stints on both sides, where those two agree and touch it,
    takes their strength. Returns label_for(stint, side), valid for the stints given.
    """
    labels = {}
    for side in SIDES:
        base = [label_for(stint, side) for stint in stints]
        for i, stint in enumerate(stints):
            label = base[i]
            if 0 < i < len(stints) - 1:
                before, after = stints[i - 1], stints[i + 1]
                if (
                    stint["end"] - stint["start"] <= max_seconds
                    and before["end"] == stint["start"] and stint["end"] == after["start"]
                    and before["period"] == stint["period"] == after["period"]
                    and base[i - 1] == base[i + 1] != label
                ):
                    label = base[i - 1]
            labels[(id(stint), side)] = label
    return lambda stint, side: labels[(id(stint), side)]


def state_label(real_for, real_against):
    """'5v5', '5v4', '4v5' ... real skaters for the team, then against it."""
    return f"{real_for}v{real_against}"


def stint_rows(game, stints, smooth_seconds=SMOOTH_SECONDS):
    """Rows for the stints table: lineups, real skaters and strength for each side.

    Strength is from skater counts with the goalie adjustment, and short blips of at
    most `smooth_seconds` between two stints of the same strength are smoothed away.
    A smoothed stint also takes the real skater counts of the stint before it, so the
    counts (and the state such as 5v5 built from them) agree with the strength.
    """
    def base(stint, side):
        return strength_from_shifts(stint, side, adjust_goalie=True)

    label_for = smoothed_label_for(stints, base, smooth_seconds)
    rows = []
    for stint in stints:
        row = {
            "game_id": stint["game_id"],
            "period": stint["period"],
            "start_game_seconds": stint["start"],
            "end_game_seconds": stint["end"],
            "seconds": stint["end"] - stint["start"],
        }
        smoothed = False
        for side in SIDES:
            skaters, goalies = stint[f"{side}_skater_ids"], stint[f"{side}_goalie_ids"]
            row[f"{side}_skater_ids"] = skaters
            row[f"{side}_goalie_ids"] = goalies
            row[f"{side}_real_skaters"] = real_skaters(len(skaters), len(goalies))
            row[f"{side}_strength"] = label_for(stint, side)
            smoothed = smoothed or row[f"{side}_strength"] != base(stint, side)
        if smoothed and rows:
            for side in SIDES:
                row[f"{side}_real_skaters"] = rows[-1][f"{side}_real_skaters"]
        rows.append(row)
    return rows


class StintIndex:
    """Find the stint that covers a moment in one game, from stint rows sorted by start.

    Goals and a few other events belong to the stint that ENDS at their second
    (end_inclusive=True, the same boundary rule as Phase 3); everything else belongs to
    the stint that STARTS at it. Returns None between periods or outside the stints.
    """

    def __init__(self, rows):
        self.rows = rows
        self.starts = [row["start_game_seconds"] for row in rows]

    def at(self, time, end_inclusive=False):
        if end_inclusive:
            index = bisect_left(self.starts, time) - 1
            if index >= 0 and time <= self.rows[index]["end_game_seconds"]:
                return self.rows[index]
        else:
            index = bisect_right(self.starts, time) - 1
            if index >= 0 and time < self.rows[index]["end_game_seconds"]:
                return self.rows[index]
        return None