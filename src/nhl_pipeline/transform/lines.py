"""Phase 6 logic: the forward line and the defense pair on the ice.

Plain Python, no file or network access. A stint (see stints.py) lists each side's skaters; this module turns
a side's skaters into the unit they form. A forward line is exactly 3 forwards and a defense pair is exactly 2
defensemen. The caller decides which stints to look at (the plan is 5v5 only) and builds `positions`, a map from
player id to 'F' (center, left or right wing) or 'D', from the boxscore's position for that game.
"""

LINE_SIZE = 3
PAIR_SIZE = 2


def units_on_ice(skater_ids, positions):
    """(line, pair) for one side's skaters.

    line is a frozenset of 3 forward ids and pair a frozenset of 2 defense ids; each is None when the count is
    different (4 forwards and 1 defenseman give neither; 3 forwards and 2 defensemen give both). A skater with no
    known position makes both None, because we cannot tell what he is.
    """
    if any(positions.get(player_id) not in ("F", "D") for player_id in skater_ids):
        return None, None
    forwards = frozenset(player_id for player_id in skater_ids if positions[player_id] == "F")
    defense = frozenset(player_id for player_id in skater_ids if positions[player_id] == "D")
    line = forwards if len(forwards) == LINE_SIZE else None
    pair = defense if len(defense) == PAIR_SIZE else None
    return line, pair
