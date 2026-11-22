"""Phase 4.1: turn play-by-play events into one row per shot attempt (pure logic, no file access).

An attempt is a goal, a shot on goal, a missed shot or a blocked shot. Everything
shot-based (Corsi, Fenwick, shots, goals for and against, later expected goals)
is a filter and a sum over these rows.

Left out: shootout events, penalty shots (not part of normal play), and every
event type that is not one of the four above (including `failed-shot-attempt`).

Conventions:
  - team_id is the event's owner team. For a blocked shot that is the SHOOTING team;
    build_shot_attempts.py checks this against the on-ice lists and prints the result.
  - x and y are turned so the shooting team always attacks toward positive x.
  - skaters_for, skaters_against, goalie_for and goalie_against come from the
    NHL's situationCode and are from the shooting team's point of view.
  - skater_ids_for / skater_ids_against come from our shift-based on-ice data
    (Phase 3). They are null for games without shift data, which still keep
    their attempt rows.
  - score_for / score_against are the score just BEFORE the attempt, so a goal
    does not count itself.
"""

from onice import parse_situation_code

ATTEMPT_TYPES = ("goal", "shot-on-goal", "missed-shot", "blocked-shot")
SCORE_EVENT_TYPE = "goal"
NO_ORDER = 10**9


def shooter_id(event):
    """The shooter: scoring player on a goal, shooting player otherwise."""
    if event["event_type"] == "goal":
        return event.get("scoring_player_id")
    return event.get("shooting_player_id")


def is_penalty_shot(skaters_for, goalie_for, skaters_against, goalie_against):
    """situationCode of a penalty shot: one skater and no goalie against no skaters and a goalie."""
    return (skaters_for, goalie_for, skaters_against, goalie_against) == (1, 0, 0, 1)


def normalize_coordinates(event, is_home):
    """Return (x, y) with the shooting team attacking toward positive x, or (None, None).

    The NHL gives the side the home team defends. If the home team defends the left
    side, home attacks right and away attacks left. Coordinates are flipped (both
    x and y) for a team attacking left.
    """
    x, y = event.get("x_coord"), event.get("y_coord")
    side = event.get("home_defending_side")
    if x is None or y is None or side not in ("left", "right"):
        return None, None
    attacks_right = is_home == (side == "left")
    return (x, y) if attacks_right else (-x, -y)


def build_game_shot_attempts(game, events, on_ice_by_event):
    """Shot-attempt rows for one game.

    `events` are staging event rows (dicts) of the game; only goals and the three
    other attempt types are used, in the NHL's order. `on_ice_by_event` maps
    event_id to the Phase 3 event_on_ice row, or is empty when the game has no
    shift data. Goals also update the running score, including penalty-shot goals.
    """
    wanted = [e for e in events if e["event_type"] in ATTEMPT_TYPES and e["period_type"] != "SO"]
    wanted.sort(key=lambda e: (e["sort_order"] is None, e["sort_order"] or 0, e["event_id"]))

    home_id, away_id = game["home_team_id"], game["away_team_id"]
    score = {home_id: 0, away_id: 0}
    rows = []
    for event in wanted:
        owner = event["event_owner_team_id"]
        if owner not in score:
            continue
        is_home = owner == home_id
        opponent = away_id if is_home else home_id
        code = parse_situation_code(event["situation_code"])
        if code is None:
            skaters_for = skaters_against = goalie_for = goalie_against = None
        elif is_home:
            skaters_for, goalie_for = code["home_skaters"], code["home_goalie"]
            skaters_against, goalie_against = code["away_skaters"], code["away_goalie"]
        else:
            skaters_for, goalie_for = code["away_skaters"], code["away_goalie"]
            skaters_against, goalie_against = code["home_skaters"], code["home_goalie"]

        penalty_shot = code is not None and is_penalty_shot(skaters_for, goalie_for, skaters_against, goalie_against)
        score_for, score_against = score[owner], score[opponent]
        if event["event_type"] == SCORE_EVENT_TYPE:
            score[owner] += 1
        if penalty_shot:
            continue

        on_ice = on_ice_by_event.get(event["event_id"])
        ids_for = ids_against = blocker_is_teammate = matches = conflict = None
        if on_ice is not None:
            side, other = ("home", "away") if is_home else ("away", "home")
            ids_for = on_ice[f"{side}_skater_ids"]
            ids_against = on_ice[f"{other}_skater_ids"]
            matches = on_ice["matches_situation"]
            conflict = on_ice["uses_conflicting_shift"]
            blocker = event.get("blocking_player_id")
            if event["event_type"] == "blocked-shot" and blocker is not None:
                if blocker in ids_for:
                    blocker_is_teammate = True
                elif blocker in ids_against:
                    blocker_is_teammate = False

        x, y = normalize_coordinates(event, is_home)
        rows.append(
            {
                "game_id": event["game_id"],
                "event_id": event["event_id"],
                "sort_order": event["sort_order"],
                "period": event["period"],
                "period_type": event["period_type"],
                "seconds_in_period": event["seconds_in_period"],
                "game_seconds": event["game_seconds"],
                "attempt_type": event["event_type"],
                "shooter_id": shooter_id(event),
                "team_id": owner,
                "opponent_team_id": opponent,
                "is_home": is_home,
                "shot_type": event.get("shot_type"),
                "zone_code": event.get("zone_code"),
                "x_raw": event.get("x_coord"),
                "y_raw": event.get("y_coord"),
                "x": x,
                "y": y,
                "goalie_id": event.get("goalie_in_net_id"),
                "blocker_id": event.get("blocking_player_id"),
                "blocker_is_teammate": blocker_is_teammate,
                "skaters_for": skaters_for,
                "skaters_against": skaters_against,
                "goalie_for": goalie_for,
                "goalie_against": goalie_against,
                "score_for": score_for,
                "score_against": score_against,
                "has_on_ice": on_ice is not None,
                "matches_situation": matches,
                "uses_conflicting_shift": conflict,
                "skater_ids_for": ids_for,
                "skater_ids_against": ids_against,
            }
        )
    return rows
