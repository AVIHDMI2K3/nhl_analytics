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
goals are end-inclusive, everything else start-inclusive.
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
TEAM_COUNT_COLUMNS = (
    ["seconds"] + [f"for_{k}" for k in KINDS] + [f"against_{k}" for k in KINDS]
)
PLAYER_COUNT_COLUMNS = (
    TEAM_COUNT_COLUMNS + [f"ind_{k}" for k in KINDS] + ["blocks_made"] + list(EVENT_COLUMNS)
)


def build_game_tables(game, stints, attempts, events=(), records=None):
    """Player and team rows for one game, plus a Counter of things worth reporting.

    `stints` are rows from stints.stint_rows. `attempts` are shot_attempts rows
    (attempt_type, game_seconds, is_home, shooter_id, blocker_id, blocker_is_teammate).
    `events` are staging event rows for the other counting stats (see event_stats.py).
    If `records` is a list, one dict is added for each goalie_shooter and each
    shooter_not_on_ice, so the cases can be looked at later.
    Notes: attempts_outside_stints (not counted anywhere), shooter_not_on_ice (the
    shooter's own attempt is still credited to him), goalie_shooter (a goalie is the
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
        stint = index.at(attempt["game_seconds"], end_inclusive=attempt["attempt_type"] == "goal")
        if stint is None:
            notes["attempts_outside_stints"] += 1
            continue
        shooting = "home" if attempt["is_home"] else "away"
        defending = other_side(shooting)
        shooting_state, defending_state = side_state(stint, shooting), side_state(stint, defending)
        shooting_team, defending_team = team_ids[shooting], team_ids[defending]

        teams[(shooting_team, *shooting_state)][f"for_{kind}"] += 1
        teams[(defending_team, *defending_state)][f"against_{kind}"] += 1
        for player_id in stint[f"{shooting}_skater_ids"]:
            players[(player_id, shooting_team, *shooting_state)][f"for_{kind}"] += 1
        for player_id in stint[f"{defending}_skater_ids"]:
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