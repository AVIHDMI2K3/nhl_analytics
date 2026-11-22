"""Phase 4.10: power-play and penalty-kill stats per skater and season (pure logic).

One row per skater, team (or combined) and situation: `pp` (power play) and `sh` (shorthanded). Two
sources, kept apart by column:

  from the play-by-play, with the strength of each goal or shot taken from the NHL's situation code
  (every game, with or without shift data):
    goals, assists_primary, assists_secondary, assists, points, shots (shots on goal, goals included)
  from our shifts (only games with shift data, games_included of games_played):
    seconds         his time on ice in the situation
    team_seconds    his team's time in the situation in the games he played
    gf, ga          team goals for and against while he was on the ice (more on-ice stats are in
                    player_season_advanced)

Why the code for individual counts: checked against the NHL's skater power-play and penalty-kill reports
and the goalies' boxscore numbers, the code's strength for goals and shots agrees with them almost
exactly (scripts/check_player_special_teams.py, scripts/diagnose_special_teams_goals.py), while strength
from the shifts is a second or two off at line changes and penalty expiries.

The per-60 rates need a count and a time on the same games, so they use included_goals, included_assists,
included_points and included_shots: the same counts restricted to the games with shift data.

  toi_per_game_seconds    seconds / games included
  team_share_pct          100 x seconds / team_seconds
  shooting_pct            100 x goals / shots (all games)
  *_per_60                count x 3600 / seconds

Rates come from the sums and are None when the divisor is zero. A traded player has a combined row.
"""

from collections import Counter, defaultdict

from advanced_stats import build_advanced_display
from base_tables import strength_from_counts

SITUATIONS = ("pp", "sh")
SHIFT_COLUMNS = ("seconds", "team_seconds", "gf", "ga")
CODE_COLUMNS = ("goals", "assists_primary", "assists_secondary", "assists", "points", "shots")
INCLUDED_COLUMNS = ("included_goals", "included_assists", "included_points", "included_shots")
COUNT_COLUMNS = SHIFT_COLUMNS[:2] + CODE_COLUMNS + SHIFT_COLUMNS[2:] + INCLUDED_COLUMNS
PER_60 = (
    ("goals", "included_goals"),
    ("assists", "included_assists"),
    ("points", "included_points"),
    ("shots", "included_shots"),
    ("gf", "gf"),
    ("ga", "ga"),
)
RATE_COLUMNS = ["toi_per_game_seconds", "team_share_pct", "shooting_pct"] + [f"{name}_per_60" for name, _ in PER_60]


def code_strength(attempt):
    """'pp', 'sh' or 'ev' for the shooting team, from the NHL situation code's counts on a shot_attempts
    row (skaters and goalies of each side). A pulled goalie (goalie 0) is an extra attacker and does not
    count as a skater, as in the NHL's power-play goal rule."""
    return strength_from_counts(
        attempt["skaters_for"], attempt["goalie_for"], attempt["skaters_against"], attempt["goalie_against"]
    )


def goal_assists(events):
    """{(game_id, event_id): (first assist player id, second assist player id)} for the goal events."""
    return {
        (e["game_id"], e["event_id"]): (e["assist1_player_id"], e["assist2_player_id"])
        for e in events
        if e["event_type"] == "goal"
    }


def individual_counts_from_code(attempts, assists, games=None):
    """{(player_id, team_id, situation): Counter} of a player's own goals, assists and shots on goal,
    for the power play and shorthanded, with the strength of each goal or shot taken from the situation
    code (see code_strength). Works for every game, with or without shift data.

    `attempts` are shot_attempts rows (goals and shots on goal are used; a row with a `strength` of its own,
    such as a shorthanded penalty-shot goal, uses that instead of the code); `assists` maps (game_id,
    event_id) of a goal to (first assist player id, second assist player id). Keys: goals,
    assists_primary, assists_secondary, assists, points, shots (shots on goal, goals included).
    When `games` ({(player_id, team_id): games with shift data}) is given, the same counts for those
    games only are kept as included_goals, included_assists, included_points and included_shots.
    """
    counts = defaultdict(Counter)

    def credit(player, team, situation, game_id, **amounts):
        total = counts[(player, team, situation)]
        in_included = games is not None and game_id in games.get((player, team), ())
        for column, amount in amounts.items():
            total[column] += amount
            if in_included and column in ("goals", "assists", "points", "shots"):
                total[f"included_{column}"] += amount

    for attempt in attempts:
        if attempt["attempt_type"] not in ("goal", "shot-on-goal"):
            continue
        situation = attempt.get("strength") or code_strength(attempt)
        if situation not in SITUATIONS:
            continue
        team, game_id = attempt["team_id"], attempt["game_id"]
        is_goal = attempt["attempt_type"] == "goal"
        if attempt["shooter_id"] is not None:
            credit(attempt["shooter_id"], team, situation, game_id, shots=1, goals=int(is_goal), points=int(is_goal))
        if is_goal:
            first, second = assists.get((game_id, attempt["event_id"]), (None, None))
            for player, kind in ((first, "assists_primary"), (second, "assists_secondary")):
                if player is not None:
                    credit(player, team, situation, game_id, assists=1, points=1, **{kind: 1})
    return counts


def shift_counts(player_rows, team_rows):
    """({(player_id, team_id, situation): Counter of SHIFT_COLUMNS}, {(player_id, team_id): games}).

    `player_rows` and `team_rows` are player_game_strength and team_game_strength rows, every state.
    A player's games are all games in which he has a row, in any state. team_seconds is his team's time
    in the situation in those games only.
    """
    team_seconds = defaultdict(int)
    for row in team_rows:
        if row["strength"] in SITUATIONS:
            team_seconds[(row["game_id"], row["team_id"], row["strength"])] += row["seconds"] or 0

    games = defaultdict(set)
    player_game = defaultdict(Counter)
    for row in player_rows:
        games[(row["player_id"], row["team_id"])].add(row["game_id"])
        if row["strength"] not in SITUATIONS:
            continue
        player_game[(row["game_id"], row["player_id"], row["team_id"], row["strength"])].update(
            {
                "seconds": row["seconds"] or 0,
                "gf": row["for_goal"] or 0,
                "ga": row["against_goal"] or 0,
            }
        )

    totals = defaultdict(Counter)
    for (game_id, player_id, team_id, situation), counts in player_game.items():
        total = totals[(player_id, team_id, situation)]
        total.update(counts)
        total["team_seconds"] += team_seconds[(game_id, team_id, situation)]
    return totals, games


def build_special_teams_counts(player_rows, team_rows, attempts=(), assists=None):
    """({(player_id, team_id, situation): Counter of COUNT_COLUMNS}, {(player_id, team_id): games included}).

    Time and on-ice goals from the shifts, individual counts from the situation code; see the module doc."""
    totals, games = shift_counts(player_rows, team_rows)
    for key, counts in individual_counts_from_code(attempts, assists or {}, games).items():
        totals[key].update(counts)
    return totals, {key: len(value) for key, value in games.items()}


def add_special_rates(row):
    row["toi_per_game_seconds"] = row["seconds"] / row["games_included"] if row["games_included"] else None
    row["team_share_pct"] = 100 * row["seconds"] / row["team_seconds"] if row["team_seconds"] else None
    row["shooting_pct"] = 100 * row["goals"] / row["shots"] if row["shots"] else None
    for name, numerator in PER_60:
        row[f"{name}_per_60"] = row[numerator] * 3600 / row["seconds"] if row["seconds"] else None
    return row


def build_special_teams_display(totals, games, season_rows, names, team_abbrevs):
    """Fan-facing rows, laid out like the advanced on-ice table (see build_advanced_display)."""
    return build_advanced_display(
        totals,
        Counter(games),
        season_rows,
        names,
        team_abbrevs,
        situations=SITUATIONS,
        columns=COUNT_COLUMNS,
        add_rates_to=add_special_rates,
    )
