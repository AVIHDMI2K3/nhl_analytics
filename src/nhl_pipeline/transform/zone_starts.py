"""Phase 6: zone starts of lines and defense pairs at 5v5 (pure logic, no file access).

A zone start is a faceoff. For each faceoff at 5v5 the line and the pair of each team on the ice are credited with the
zone of the faceoff in their own terms: oz (offensive), dz (defensive) or nz (neutral). The event's zone_code is the
view of the team that owns the event (the winner), so the other team gets the flipped zone (offensive <-> defensive).

Who is on the ice: a faceoff is at the moment of a stoppage, when the players who stepped on for it have a shift that
STARTS at that second and the players who left have one that ENDS at it. So the stint that starts at the faceoff's
second (StintIndex.at, start-inclusive, like every event except goals and defending-side attempts) is the one used.
A faceoff is at 5v5 when its situationCode says so (five skaters and a goalie each side), else when its stint does.

oz_start_pct = 100 x oz / (oz + dz): the neutral zone is left out, as on the usual public sites. Above 50 means the
unit was started in the offensive zone more than in its own.
"""

from collections import Counter, defaultdict

from faceoffs import FLIP
from line_tables import is_five_on_five, units_of
from onice import parse_situation_code
from stints import StintIndex, side_state

ZONE_NAMES = {"O": "oz", "D": "dz", "N": "nz"}
ZONE_COLUMNS = ("oz", "dz", "nz")


def faceoff_is_five_on_five(event, stint):
    code = parse_situation_code(event.get("situation_code"))
    if code is None:
        return is_five_on_five(side_state(stint, "home"))
    return (code["away_skaters"], code["home_skaters"], code["away_goalie"], code["home_goalie"]) == (5, 5, 1, 1)


def unit_zone_starts(game, stints, events, positions):
    """({(team_id, unit_type, player ids): Counter of 'oz', 'dz', 'nz'}, number of 5v5 faceoff sides counted).

    `events` are the game's staging events (only event_type 'faceoff' with an owner team, a zone_code and a
    game_seconds are used) and `positions` maps a player id to 'F' or 'D'. A faceoff with no stint at its second
    (between periods) or a different strength is skipped."""
    team_ids = {"home": game["home_team_id"], "away": game["away_team_id"]}
    index = StintIndex(stints)
    totals = defaultdict(Counter)
    sides_counted = 0
    for event in events:
        if event.get("event_type") != "faceoff" or event.get("zone_code") not in FLIP:
            continue
        owner = event.get("event_owner_team_id")
        if owner not in team_ids.values():
            continue
        stint = index.at(event["game_seconds"])
        if stint is None or not faceoff_is_five_on_five(event, stint):
            continue
        for side, team_id in team_ids.items():
            zone = event["zone_code"] if team_id == owner else FLIP[event["zone_code"]]
            sides_counted += 1
            for unit in units_of(stint[f"{side}_skater_ids"], positions):
                totals[(team_id, *unit)][ZONE_NAMES[zone]] += 1
    return totals, sides_counted


def oz_start_pct(oz, dz):
    return 100 * oz / (oz + dz) if oz + dz else None


def season_zone_rows(game_totals):
    """Season rows from a list of per-game results: one row per team and unit with oz, dz, nz and oz_start_pct."""
    totals = defaultdict(Counter)
    for game in game_totals:
        for key, counts in game.items():
            totals[key].update(counts)
    rows = []
    for (team_id, unit_type, player_ids), c in sorted(totals.items()):
        rows.append(
            {
                "team_id": team_id,
                "unit_type": unit_type,
                "player_ids": list(player_ids),
                "oz": c["oz"],
                "dz": c["dz"],
                "nz": c["nz"],
                "oz_start_pct": oz_start_pct(c["oz"], c["dz"]),
            }
        )
    return rows
