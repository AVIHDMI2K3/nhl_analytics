"""Phase 4.9: team season basic stats (pure logic).

The record and goals come from the games table (the final scores, as in the NHL standings, so
a shootout win counts one goal for the winner). Shots, hits, blocks, giveaways, takeaways,
penalty minutes and power-play goals come from adding up the boxscore. Every regular-season
game with a boxscore counts, including the 57 games in 2024-25 that have no shift data.

  wins, losses, ot_losses   a loss in overtime or a shootout is an overtime loss
  points                    2 for a win, 1 for an overtime loss
  regulation_wins, row      wins in regulation / in regulation or overtime (not shootout)
  goals_for, goals_against  final scores
  shots_for                 the team's skaters' shots on goal; shots_against is the opponent's
  pp_goals_for              the team's power-play goals (skaters)
  pp_goals_against          power-play goals the team allowed (goalies' power_play_goals_against)

Not here yet: power-play and penalty-kill percentages (they need power-play opportunities) and
faceoff percentage.
"""

from collections import Counter, defaultdict

OVERTIME_TYPES = ("OT", "SO")
REGULAR_SEASON = 2
BOX_SUMS = ("hits", "blocked_shots", "giveaways", "takeaways", "pim")
COUNT_COLUMNS = (
    "wins",
    "losses",
    "ot_losses",
    "points",
    "regulation_wins",
    "row",
    "goals_for",
    "goals_against",
    "shots_for",
    "shots_against",
    "pp_goals_for",
    "pp_goals_against",
) + BOX_SUMS


def build_team_basic(games, box_rows):
    """(rows, notes). `games` are games rows; `box_rows` are boxscore_players rows.

    Notes: games_without_score (left out of the record). Rows have games_played and COUNT_COLUMNS.
    """
    regular = {g["game_id"]: g for g in games if g["game_type"] == REGULAR_SEASON and g["has_boxscore"]}
    notes = Counter()
    played = Counter()
    totals = defaultdict(Counter)

    for game in regular.values():
        if game["home_score"] is None or game["away_score"] is None:
            notes["games_without_score"] += 1
            continue
        for team, other, goals_for, goals_against in (
            (game["home_team_id"], game["away_team_id"], game["home_score"], game["away_score"]),
            (game["away_team_id"], game["home_team_id"], game["away_score"], game["home_score"]),
        ):
            played[team] += 1
            counts = totals[team]
            counts["goals_for"] += goals_for
            counts["goals_against"] += goals_against
            if goals_for > goals_against:
                counts["wins"] += 1
                counts["points"] += 2
                if game["last_period_type"] != "SO":
                    counts["row"] += 1
                if game["last_period_type"] not in OVERTIME_TYPES:
                    counts["regulation_wins"] += 1
            elif game["last_period_type"] in OVERTIME_TYPES:
                counts["ot_losses"] += 1
                counts["points"] += 1
            else:
                counts["losses"] += 1

    counted = {g for g, game in regular.items() if game["home_score"] is not None and game["away_score"] is not None}
    shots_by_game_team = Counter()
    for row in box_rows:
        if row["game_id"] not in counted:
            continue
        team = row["team_id"]
        totals[team]["pim"] += row["pim"] or 0
        if row["player_group"] == "goalies":
            totals[team]["pp_goals_against"] += row["power_play_goals_against"] or 0
            continue
        shots_by_game_team[(row["game_id"], team)] += row["sog"] or 0
        totals[team]["shots_for"] += row["sog"] or 0
        totals[team]["pp_goals_for"] += row["power_play_goals"] or 0
        for column in ("hits", "blocked_shots", "giveaways", "takeaways"):
            totals[team][column] += row[column] or 0
    for game_id in counted:
        game = regular[game_id]
        home, away = game["home_team_id"], game["away_team_id"]
        totals[home]["shots_against"] += shots_by_game_team[(game_id, away)]
        totals[away]["shots_against"] += shots_by_game_team[(game_id, home)]

    rows = []
    for team in sorted(played):
        row = {"team_id": team, "games_played": played[team]}
        row.update({column: totals[team][column] for column in COUNT_COLUMNS})
        row["goal_diff"] = row["goals_for"] - row["goals_against"]
        row["points_pct"] = row["points"] / (2 * played[team])
        for name in ("goals_for", "goals_against", "shots_for", "shots_against"):
            row[f"{name}_per_game"] = row[name] / played[team]
        rows.append(row)
    return rows, notes
