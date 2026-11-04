"""Phase 4.4: the other counting stats, from play-by-play events (pure logic, no file access).

Each event is given to the stint it falls in, with the Phase 3 boundary rule for its type
(goals, penalties and a few others are end-inclusive, the rest start-inclusive). The player
named in the event is credited in his own team's state for that stint, so the stat lands in
the same player-game-state row as his time on ice.

Columns added to the player table:
  assists_primary, assists_secondary   assist1 and assist2 of a goal
  hits_made, hits_taken                hitter and the player hit
  giveaways, takeaways                 the player named in the event
  faceoff_wins, faceoff_losses         winner and loser of a faceoff
  penalties_taken, penalties_drawn     the penalized player and the player who drew it
  penalty_minutes                      minutes of the penalties the player took (a bench
                                       penalty has no penalized player, so it counts for nobody)

Rules:
  - Shootout events are left out.
  - Goalies get no row in the skater table; their events are counted in the notes
    (goalie_event). Goalies do have giveaways.
  - A player named in an event who is not in either side's skaters at that second (a
    one-second shift boundary) is still credited, on the side the NHL's event owner team
    implies for his role (the same team as the owner for the hitter, the giveaway player,
    the takeaway player, the faceoff winner, the penalized player and the assisters; the
    other team for the player hit, the faceoff loser and the player who drew the penalty).
    This is counted as actor_not_on_ice.
  - For players who ARE on the ice, the notes record whether the owner team agrees with the
    team he is on, per column (<column>:team_matches_owner / <column>:team_differs_from_owner),
    which is how that assumption about the owner is checked.
  - Shift-based events outside every stint are counted as events_outside_stints.
"""

from onice import RULE_END_INCLUSIVE, rule_for
from stints import other_side, side_state

# event type -> (column, id field in the event, same team as the owner, field with the amount)
ROLES = {
    "goal": [
        ("assists_primary", "assist1_player_id", True, None),
        ("assists_secondary", "assist2_player_id", True, None),
    ],
    "hit": [
        ("hits_made", "hitting_player_id", True, None),
        ("hits_taken", "hittee_player_id", False, None),
    ],
    "giveaway": [("giveaways", "player_id", True, None)],
    "takeaway": [("takeaways", "player_id", True, None)],
    "faceoff": [
        ("faceoff_wins", "winning_player_id", True, None),
        ("faceoff_losses", "losing_player_id", False, None),
    ],
    "penalty": [
        ("penalties_taken", "committed_by_player_id", True, None),
        ("penalties_drawn", "drawn_by_player_id", False, None),
        ("penalty_minutes", "committed_by_player_id", True, "penalty_minutes"),
    ],
}
EVENT_COLUMNS = tuple(dict.fromkeys(column for roles in ROLES.values() for column, *_ in roles))


def player_side(stint, player_id):
    """'home' or 'away' if the player is a skater in the stint, 'goalie' if a goalie, else None."""
    for side in ("home", "away"):
        if player_id in stint[f"{side}_skater_ids"]:
            return side
    for side in ("home", "away"):
        if player_id in stint[f"{side}_goalie_ids"]:
            return "goalie"
    return None


def credit_event_stats(game, index, events, players, notes):
    """Add the event stats of one game to `players` (a dict of Counters keyed like the player
    table) and to `notes`. `index` is a StintIndex of the game's stints."""
    team_ids = {"home": game["home_team_id"], "away": game["away_team_id"]}
    for event in events:
        roles = ROLES.get(event["event_type"])
        if roles is None or event["period_type"] == "SO" or event["game_seconds"] is None:
            continue
        end_inclusive = rule_for(event["event_type"]) == RULE_END_INCLUSIVE
        stint = index.at(event["game_seconds"], end_inclusive=end_inclusive)
        if stint is None:
            notes["events_outside_stints"] += 1
            continue
        owner = event["event_owner_team_id"]
        owner_side = next((s for s in ("home", "away") if team_ids[s] == owner), None)
        for column, field, same_team, amount_field in roles:
            player_id = event.get(field)
            if player_id is None:
                continue
            side = player_side(stint, player_id)
            if side == "goalie":
                notes["goalie_event"] += 1
                continue
            expected = None
            if owner_side is not None:
                expected = owner_side if same_team else other_side(owner_side)
            if side is None:
                if expected is None:
                    notes["actor_unplaceable"] += 1
                    continue
                notes["actor_not_on_ice"] += 1
                side = expected
            elif expected is not None:
                notes[f"{column}:team_{'matches' if side == expected else 'differs_from'}_owner"] += 1
            amount = 1 if amount_field is None else (event.get(amount_field) or 0)
            players[(player_id, team_ids[side], *side_state(stint, side))][column] += amount