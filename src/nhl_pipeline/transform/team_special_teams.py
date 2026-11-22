"""Phase 4.11: team power-play and penalty-kill numbers (pure logic, no file access).

For every team and game:
  pp_opportunities    power plays the team got, counted from the penalty events (see penalty_opportunities)
  pp_goals            goals the team scored on the power play (strength from the NHL situation code)
  times_shorthanded   the other team's opportunities
  pk_goals_against    power-play goals the other team scored (the team's own penalty-kill failures)
  sh_goals_for        goals the team scored while shorthanded
  sh_goals_against    goals the team allowed while on the power play
Season rows add these up and give power-play % (100 x goals / opportunities) and penalty-kill %
(100 x (1 - goals against / times shorthanded)).

Penalty-shot goals are not in shot_attempts. The NHL counts one scored by a shorthanded team as a shorthanded
goal (all three disagreements left in 2024 and 2025 were this), and does not count one as a power-play goal
(power-play goals match with them left out), so only the shorthanded ones are added, found from the events
(situationCode 1010 or 0101) with the team's strength taken from the stint.

Empty-net goals are included (a goal into an empty net on the power play is a power-play goal, as in
the NHL's reports), unlike the goalies' power-play goals against in the boxscore.

Opportunities are our count, not the NHL's: the NHL does not publish its rule. Checked against the
NHL's per-game team reports with scripts/check_team_special_teams.py; the rule below matches the NHL's
count in 97-98% of team-games and in the league total to within 0.3% (see docs/data_notes.md).
"""

from collections import Counter, defaultdict

from onice import parse_situation_code
from special_teams import code_strength

COUNTED_MINUTES = (
    2,
    4,
    5,
)  # minors, double minors and majors; misconducts (10) and penalty shots (0) give no power play
GAME_COLUMNS = (
    "pp_opportunities",
    "pp_goals",
    "times_shorthanded",
    "pk_goals_against",
    "sh_goals_for",
    "sh_goals_against",
)
SEASON_COLUMNS = GAME_COLUMNS
RATE_COLUMNS = ("pp_pct", "pk_pct", "pp_opportunities_per_game", "times_shorthanded_per_game")


def prepare_penalties(events, games):
    """Penalty rows with the opponent and whether the game went to overtime, from staging event rows
    (game_id, event_type, period_type, game_seconds, event_owner_team_id, penalty_minutes) and games
    ({game_id: row with home_team_id and away_team_id})."""
    overtime = {e["game_id"] for e in events if e["period_type"] == "OT"}
    rows = []
    for event in events:
        if event["event_type"] != "penalty":
            continue
        game = games[event["game_id"]]
        owner = event["event_owner_team_id"]
        rows.append(
            {
                "game_id": event["game_id"],
                "game_seconds": event["game_seconds"],
                "period_type": event["period_type"],
                "event_owner_team_id": owner,
                "penalty_minutes": event["penalty_minutes"],
                "opponent_team_id": game["away_team_id"] if owner == game["home_team_id"] else game["home_team_id"],
                "game_has_ot": event["game_id"] in overtime,
            }
        )
    return rows


def penalty_opportunities(penalties):
    """({(game_id, team_id): opportunities}, {(game_id, team_id): times shorthanded}) from prepare_penalties rows.

    The rule, found by comparing with the NHL's per-game counts:
      - a 2- or 5-minute penalty is one power play for the other team; a 4-minute double minor is two
        2-minute penalties, so two
      - penalties of the same length given to both teams at the same second cancel one for one
        (coincident minors, and the pair of majors in a fight)
      - penalties at exactly the end of regulation (3600 s) do not count in a game without overtime
      - misconducts (10 minutes) and penalty shots (0) do not count
    """
    taken = Counter()  # (game, second, minutes, penalized team) -> number of penalties
    opponent = {}
    for row in penalties:
        minutes = row["penalty_minutes"]
        if minutes not in COUNTED_MINUTES:
            continue
        if row["game_seconds"] == 3600 and row["period_type"] == "REG" and not row["game_has_ot"]:
            continue
        parts = 1
        if minutes == 4:
            minutes, parts = 2, 2
        key = (row["game_id"], row["game_seconds"], minutes, row["event_owner_team_id"])
        taken[key] += parts
        opponent[key] = row["opponent_team_id"]
    opportunities, shorthanded = Counter(), Counter()
    for key, number in taken.items():
        game, second, minutes, team = key
        number = max(number - taken.get((game, second, minutes, opponent[key]), 0), 0)
        if number:
            shorthanded[(game, team)] += number
            opportunities[(game, opponent[key])] += number
    return opportunities, shorthanded


def goals_by_strength(attempts):
    """{(game_id, team_id): Counter(pp, sh)} of the goals each team scored on the power play and
    shorthanded, with the strength of each goal from the NHL situation code (see special_teams.code_strength).
    `attempts` are shot_attempts rows (attempt_type, game_id, team_id of the shooting team and the code counts)."""
    goals = defaultdict(Counter)
    for attempt in attempts:
        if attempt["attempt_type"] != "goal":
            continue
        strength = code_strength(attempt)
        if strength != "ev":
            goals[(attempt["game_id"], attempt["team_id"])][strength] += 1
    return goals


def penalty_shot_goals(events, games):
    """[{game_id, game_seconds, team_id, is_home}] for the goals scored on a penalty shot (not in a shootout):
    the situationCode shows one skater and no goalie for the scoring team against no skaters and a goalie
    (1010 or 0101), the same test onice.game_plus_minus uses. `events` are staging event rows (game_id,
    event_type, period_type, game_seconds, event_owner_team_id, situation_code)."""
    rows = []
    for event in events:
        if event["event_type"] != "goal" or event["period_type"] == "SO":
            continue
        code = parse_situation_code(event["situation_code"])
        game = games.get(event["game_id"])
        if code is None or game is None:
            continue
        home = event["event_owner_team_id"] == game["home_team_id"]
        side, other = ("home", "away") if home else ("away", "home")
        if (code[f"{side}_skaters"], code[f"{side}_goalie"], code[f"{other}_skaters"], code[f"{other}_goalie"]) == (
            1,
            0,
            0,
            1,
        ):
            rows.append(
                {
                    "game_id": event["game_id"],
                    "event_id": event.get("event_id"),
                    "game_seconds": event["game_seconds"],
                    "team_id": event["event_owner_team_id"],
                    "is_home": home,
                    "shooter_id": event.get("scoring_player_id"),
                }
            )
    return rows


def stint_strength(stints, second, is_home):
    """'pp', 'sh' or 'ev' for one side from the stint covering `second` (start < second <= end, as a goal
    belongs to the stint that ends on its second), or None if no stint covers it. `stints` are the rows of
    one game with start_game_seconds, end_game_seconds, home_strength and away_strength."""
    for stint in stints:
        if stint["start_game_seconds"] < second <= stint["end_game_seconds"]:
            return stint["home_strength" if is_home else "away_strength"]
    return None


def shorthanded_penalty_shot_goals(shots, stints_by_game):
    """{(game_id, team_id): number} of the penalty-shot goals scored by a team that was shorthanded."""
    counts = Counter()
    for shot in shots:
        if stint_strength(stints_by_game.get(shot["game_id"], ()), shot["game_seconds"], shot["is_home"]) == "sh":
            counts[(shot["game_id"], shot["team_id"])] += 1
    return counts


def shorthanded_penalty_shot_attempts(shots, stints_by_game):
    """shot_attempts-like goal rows (with strength 'sh' set) for the penalty-shot goals scored by a shorthanded
    team, to be counted with the other goals of the skater special-teams table (see
    special_teams.individual_counts_from_code, which uses a row's `strength` when it has one)."""
    return [
        {
            "attempt_type": "goal",
            "game_id": s["game_id"],
            "event_id": s["event_id"],
            "shooter_id": s["shooter_id"],
            "team_id": s["team_id"],
            "strength": "sh",
        }
        for s in shots
        if stint_strength(stints_by_game.get(s["game_id"], ()), s["game_seconds"], s["is_home"]) == "sh"
    ]


def build_team_game_rows(games, penalties, attempts, shorthanded_shots=None):
    """One row per team and game (every game, every team): the GAME_COLUMNS plus game_id, team_id and
    opponent_team_id. `shorthanded_shots` is the result of shorthanded_penalty_shot_goals. `games`
    {game_id: row with home_team_id and away_team_id}, `penalties` from
    prepare_penalties, `attempts` shot_attempts rows."""
    opportunities, shorthanded = penalty_opportunities(penalties)
    goals = goals_by_strength(attempts)
    for key, number in (shorthanded_shots or {}).items():
        goals[key]["sh"] += number
    rows = []
    for game_id in sorted(games):
        home, away = games[game_id]["home_team_id"], games[game_id]["away_team_id"]
        for team, other in ((home, away), (away, home)):
            mine, theirs = goals.get((game_id, team), Counter()), goals.get((game_id, other), Counter())
            rows.append(
                {
                    "game_id": game_id,
                    "team_id": team,
                    "opponent_team_id": other,
                    "pp_opportunities": opportunities.get((game_id, team), 0),
                    "pp_goals": mine["pp"],
                    "times_shorthanded": shorthanded.get((game_id, team), 0),
                    "pk_goals_against": theirs["pp"],
                    "sh_goals_for": mine["sh"],
                    "sh_goals_against": theirs["sh"],
                }
            )
    return rows


def percent(part, whole):
    return 100 * part / whole if whole else None


def build_team_season_rows(game_rows, abbrevs=None):
    """One row per team: games_played, the SEASON_COLUMNS summed, and the RATE_COLUMNS."""
    totals = defaultdict(Counter)
    for row in game_rows:
        total = totals[row["team_id"]]
        total["games_played"] += 1
        for column in SEASON_COLUMNS:
            total[column] += row[column]
    rows = []
    for team_id in sorted(totals):
        total = totals[team_id]
        row = {
            "team_id": team_id,
            "team": (abbrevs or {}).get(team_id, str(team_id)),
            "games_played": total["games_played"],
        }
        row.update({column: total[column] for column in SEASON_COLUMNS})
        row["pp_pct"] = percent(total["pp_goals"], total["pp_opportunities"])
        killed = percent(total["pk_goals_against"], total["times_shorthanded"])
        row["pk_pct"] = None if killed is None else 100 - killed
        row["pp_opportunities_per_game"] = total["pp_opportunities"] / total["games_played"]
        row["times_shorthanded_per_game"] = total["times_shorthanded"] / total["games_played"]
        rows.append(row)
    return rows
