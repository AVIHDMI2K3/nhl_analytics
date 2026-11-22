"""Phase 4.3: base tables (pure logic, no file access).

Two long tables per season, built from the stints (Phase 4.2) and the shot attempts
(Phase 4.1). Everything in them is a count or a number of seconds, so any season, date
range or team is a sum, and ratios such as CF% are computed from the sums later.

  player_game_strength  one row per skater, game and state: seconds on the ice, attempts
                      for and against while on the ice, and the skater's own attempts
  team_game_strength    one row per team, game and state: seconds and attempts for and
                      against. Off-ice numbers are the team's minus the skater's.

A state is the team's view of the ice during a stint:
  strength            ev / pp / sh, the rule validated against the NHL's time on ice
  skaters_for         skaters the team had on the ice (goalie not counted)
  skaters_against     skaters the opponent had on the ice
  goalies_for         goalies the team had on the ice (0 when the goalie is pulled)
  goalies_against     goalies the opponent had on the ice
So 5v5 is skaters 5 and 5 with a goalie each, and a six-skater empty-net stretch is a
different state from 5v5 although both are "ev". The rolled-up groups the fan view
needs are made from states at query time.

Columns that count attempts, with kind goal, sog (shot on goal that was not a goal),
miss or block:
  for_<kind>, against_<kind>   attempts by the team / against it while the player (or the
                               team, in the team table) was on the ice
  ind_<kind>                   the player's own attempts; his shots on goal in the
                               boxscore are ind_goal + ind_sog
  blocks_made                  shots blocked by the player, not counting a block of a
                               teammate's shot
An attempt belongs to the stint it falls in, with the same boundary rule as Phase 3:
goals are end-inclusive, everything else start-inclusive. Two exceptions, chosen because they
agree best with Natural Stat Trick's per-skater Corsi in 2023 and 2025 (see docs/data_notes.md):
the skaters of the defending team for an attempt that is not a goal, and the shooting team's
skaters for a shot on goal, are taken from the stint that ENDS at the attempt's second
(end-inclusive). The stint decides WHO was on the
ice (the skaters credited); the state (strength and skater counts) the attempt is counted
under comes from the NHL situationCode on the attempt when the attempt row has it
(skaters_for, skaters_against, goalie_for, goalie_against, from the shooting team's view),
because the shift-based strength is a second or two off at line changes and penalty expiries.
Seconds always use the stint's own state. Without those fields the stint's state is used.
"""

from collections import Counter, defaultdict

from event_stats import EVENT_COLUMNS, credit_event_stats
from stints import SIDES, StintIndex, other_side, side_state

KIND_BY_ATTEMPT = {
    "goal": "goal",
    "shot-on-goal": "sog",
    "missed-shot": "miss",
    "blocked-shot": "block",
}
KINDS = tuple(KIND_BY_ATTEMPT.values())
STATE_COLUMNS = ("strength", "skaters_for", "skaters_against", "goalies_for", "goalies_against")
TEAM_COUNT_COLUMNS = ["seconds"] + [f"for_{k}" for k in KINDS] + [f"against_{k}" for k in KINDS]
PLAYER_COUNT_COLUMNS = TEAM_COUNT_COLUMNS + [f"ind_{k}" for k in KINDS] + ["blocks_made"] + list(EVENT_COLUMNS)


CODE_FIELDS = ("skaters_for", "skaters_against", "goalie_for", "goalie_against")
MIRROR = {"pp": "sh", "sh": "pp", "ev": "ev"}


def strength_from_counts(skaters_for, goalies_for, skaters_against, goalies_against):
    """'pp', 'sh' or 'ev' for the "for" side. A pulled goalie (0 goalies) is an extra attacker and
    does not count as a skater, as in the NHL's power-play goal rule."""
    mine = skaters_for - (1 if goalies_for == 0 else 0)
    theirs = skaters_against - (1 if goalies_against == 0 else 0)
    return "pp" if mine > theirs else "sh" if mine < theirs else "ev"


def code_states(attempt):
    """(shooting side state, defending side state) from the situationCode counts on a shot_attempts row,
    each as (strength, skaters_for, skaters_against, goalies_for, goalies_against), or None when the
    row has no counts."""
    values = [attempt.get(name) for name in CODE_FIELDS]
    if any(value is None for value in values):
        return None
    sf, sa, gf, ga = values
    strength = strength_from_counts(sf, gf, sa, ga)
    return (strength, sf, sa, gf, ga), (MIRROR[strength], sa, sf, ga, gf)


def credited_stints(index, attempt, kind):
    """(stint, shooting_stint, defending_stint) for one shot attempt, or None if it is outside every stint.

    `stint` is the one the attempt falls in (a goal belongs to the stint ending at its second, any other attempt to
    the stint starting at it). The skaters credited come from shooting_stint (the shooting team's) and
    defending_stint (the other team's): the stint ending at the attempt's second for the defending team on any
    non-goal attempt and for the shooting team on a shot on goal (see the module docstring)."""
    stint = index.at(attempt["game_seconds"], end_inclusive=kind == "goal")
    if stint is None:
        return None
    defending_stint = shooting_stint = stint
    if kind != "goal":
        defending_stint = index.at(attempt["game_seconds"], end_inclusive=True) or stint
    if kind == "sog":
        shooting_stint = defending_stint
    return stint, shooting_stint, defending_stint


def build_game_tables(game, stints, attempts, events=(), records=None):
    """Player and team rows for one game, plus a Counter of things worth reporting.

    `stints` are rows from stints.stint_rows. `attempts` are shot_attempts rows
    (attempt_type, game_seconds, is_home, shooter_id, blocker_id, blocker_is_teammate).
    `events` are staging event rows for the other counting stats (see event_stats.py).
    If `records` is a list, one dict is added for each goalie_shooter and each
    shooter_not_on_ice, so the cases can be looked at later.
    Notes: attempts_outside_stints (not counted anywhere), shooter_not_on_ice (the
    shooter's own attempt is still credited to him), state_from_code and
    state_differs_from_stint (attempts counted under the situationCode's state, and how many of
    them differ from the stint's state), goalie_shooter (a goalie is the
    shooter, so the attempt counts for the team and the skaters on the ice but the goalie
    gets no row in the skater table).
    """
    team_ids = {"home": game["home_team_id"], "away": game["away_team_id"]}
    players = defaultdict(Counter)
    teams = defaultdict(Counter)
    notes = Counter()

    for stint in stints:
        for side in SIDES:
            state = side_state(stint, side)
            teams[(team_ids[side], *state)]["seconds"] += stint["seconds"]
            for player_id in stint[f"{side}_skater_ids"]:
                players[(player_id, team_ids[side], *state)]["seconds"] += stint["seconds"]

    index = StintIndex(stints)
    for attempt in attempts:
        kind = KIND_BY_ATTEMPT.get(attempt["attempt_type"])
        if kind is None:
            continue
        credited = credited_stints(index, attempt, kind)
        if credited is None:
            notes["attempts_outside_stints"] += 1
            continue
        stint, shooting_stint, defending_stint = credited
        shooting = "home" if attempt["is_home"] else "away"
        defending = other_side(shooting)
        shooting_state, defending_state = side_state(stint, shooting), side_state(stint, defending)
        from_code = code_states(attempt)
        if from_code is not None:
            notes["state_from_code"] += 1
            if from_code != (shooting_state, defending_state):
                notes["state_differs_from_stint"] += 1
            shooting_state, defending_state = from_code
        shooting_team, defending_team = team_ids[shooting], team_ids[defending]

        teams[(shooting_team, *shooting_state)][f"for_{kind}"] += 1
        teams[(defending_team, *defending_state)][f"against_{kind}"] += 1
        for player_id in shooting_stint[f"{shooting}_skater_ids"]:
            players[(player_id, shooting_team, *shooting_state)][f"for_{kind}"] += 1
        for player_id in defending_stint[f"{defending}_skater_ids"]:
            players[(player_id, defending_team, *defending_state)][f"against_{kind}"] += 1

        shooter = attempt["shooter_id"]
        if shooter is not None:
            if shooter in stint[f"{shooting}_goalie_ids"]:
                notes["goalie_shooter"] += 1  # counts for the team and the skaters, not for the goalie
                note_case(records, "goalie_shooter", game, attempt)
            else:
                if shooter not in stint[f"{shooting}_skater_ids"]:
                    notes["shooter_not_on_ice"] += 1
                    note_case(records, "shooter_not_on_ice", game, attempt)
                players[(shooter, shooting_team, *shooting_state)][f"ind_{kind}"] += 1
        blocker = attempt.get("blocker_id")
        if kind == "block" and blocker is not None and attempt.get("blocker_is_teammate") is False:
            players[(blocker, defending_team, *defending_state)]["blocks_made"] += 1

    credit_event_stats(game, index, events, players, notes)

    return (
        table_rows(game, players, PLAYER_COUNT_COLUMNS, "player_id"),
        table_rows(game, teams, TEAM_COUNT_COLUMNS, None),
        notes,
    )


def note_case(records, kind, game, attempt):
    if records is not None:
        records.append(
            {
                "kind": kind,
                "game_id": game["game_id"],
                "event_id": attempt.get("event_id"),
                "attempt_type": attempt["attempt_type"],
                "game_seconds": attempt["game_seconds"],
                "player_id": attempt["shooter_id"],
            }
        )


def table_rows(game, accumulator, count_columns, player_key):
    rows = []
    for key in sorted(accumulator):
        if player_key:
            player_id, team_id, *state = key
        else:
            team_id, *state = key
        row = {"game_id": game["game_id"]}
        if player_key:
            row[player_key] = player_id
        row["team_id"] = team_id
        row.update(dict(zip(STATE_COLUMNS, state)))
        for column in count_columns:
            row[column] = accumulator[key][column]
        rows.append(row)
    return rows


def plus_minus(row):
    """Plus/minus from one player row, by the NHL rule: goals at even strength count both
    ways, shorthanded goals for count, power-play goals against count against, and
    power-play goals scored and shorthanded goals allowed count for nobody."""
    if row["strength"] == "ev":
        return row["for_goal"] - row["against_goal"]
    if row["strength"] == "pp":
        return -row["against_goal"]
    return row["for_goal"]
