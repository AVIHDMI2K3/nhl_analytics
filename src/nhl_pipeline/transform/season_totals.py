"""Phase 4.5: season totals for skaters, straight from the NHL boxscore (pure logic).

The boxscore gives each skater's simple numbers for every game: goals, assists, points,
plus/minus, penalty minutes, hits, shots, blocked shots, giveaways, takeaways, time on ice.
We checked it against the NHL's official game reports (docs/data_notes.md), so these totals
are taken from it as they are and not worked out again from the play-by-play.

One row per skater and team for the season, so a player traded mid-season has two rows. The
fan view combines them. Games played is the number of games in which the skater had time on ice. Checked against the
NHL's skater report, this matches for every skater in all three seasons; counting every game
he is listed in was off by one for one skater in 2024 and in 2025.
Faceoff percentage is not here: the boxscore gives only a percentage per game, which cannot be
added up. Stats that depend on who was on the ice come from the stints (base_tables.py).

Goalies are separate (build_goalie_season_totals): one row per goalie and team, from the same
boxscore. Games played is the number of games with time on ice, games started the number of games
he started, and wins, losses and overtime losses come from the boxscore's decision (W, L, O; O is
an overtime or shootout loss). Shots against by strength are read from the boxscore's "saves/shots"
text. A shutout is a game in which he played all of his team's goalie time, allowed no goal and did not lose in
regulation (a win, or a shootout loss: the shootout goals do not count as goals against).
Save percentage and goals-against average are rates, worked out in season_display.py.
"""

from collections import Counter, defaultdict

SUM_COLUMNS = (
    "goals", "assists", "points", "plus_minus", "pim", "hits", "power_play_goals",
    "sog", "blocked_shots", "giveaways", "takeaways", "toi_seconds", "shifts",
)
REGULAR_SEASON = 2
GOALIE_SUM_COLUMNS = (
    "toi_seconds", "pim", "shots_against", "saves", "goals_against",
    "even_strength_shots_against", "even_strength_goals_against",
    "power_play_shots_against", "power_play_goals_against",
    "shorthanded_shots_against", "shorthanded_goals_against",
)
GOALIE_COUNT_COLUMNS = ("games_started", "wins", "losses", "ot_losses", "shutouts")
GOALIE_COLUMNS = GOALIE_SUM_COLUMNS + GOALIE_COUNT_COLUMNS
DECISION_COLUMNS = {"W": "wins", "L": "losses", "O": "ot_losses"}
SHOTS_BY_STRENGTH = (  # our column <- the boxscore's "saves/shots" text column
    "even_strength_shots_against", "power_play_shots_against", "shorthanded_shots_against",
)


def build_player_season_totals(box_rows, regular_game_ids, game_dates=None):
    """Rows for skaters only (goalies are left out), games in `regular_game_ids` only.

    `box_rows` are boxscore_players rows. A missing number counts as 0. `game_dates` (game id
    to an ISO date string) gives each row the date of the first game he played for the team,
    so a traded player's teams can be put in order.
    """
    totals = defaultdict(Counter)
    positions = defaultdict(Counter)
    names = {}
    games = defaultdict(set)
    first_dates = {}
    for row in box_rows:
        if row["player_group"] == "goalies" or row["game_id"] not in regular_game_ids:
            continue
        key = (row["player_id"], row["team_id"])
        if (row["toi_seconds"] or 0) > 0:
            games[key].add(row["game_id"])
            date = (game_dates or {}).get(row["game_id"])
            if date is not None and (key not in first_dates or date < first_dates[key]):
                first_dates[key] = date
        names[key] = row["name"]
        positions[key][row["position"]] += 1
        for column in SUM_COLUMNS:
            totals[key][column] += row[column] or 0
    rows = []
    for key in sorted(totals):
        player_id, team_id = key
        row = {
            "player_id": player_id,
            "team_id": team_id,
            "name": names[key],
            "position": positions[key].most_common(1)[0][0],
            "games_played": len(games[key]),
            "first_game_date": first_dates.get(key),
        }
        row.update({column: totals[key][column] for column in SUM_COLUMNS})
        rows.append(row)
    return rows

def shots_in(text):
    """Shots from the boxscore's 'saves/shots' text: '15/17' is 17. Missing or malformed is 0."""
    if not isinstance(text, str):
        return 0
    _, _, shots = text.partition("/")
    return int(shots) if shots.isdigit() else 0


def build_goalie_season_totals(box_rows, regular_game_ids, game_dates=None):
    """Rows for goalies only, one per goalie and team, games in `regular_game_ids` only.

    `box_rows` are boxscore_players rows. A goalie who dressed but did not play has a row with
    zero games played. `game_dates` works as in build_player_season_totals.
    """
    goalie_rows = [
        row for row in box_rows if row["player_group"] == "goalies" and row["game_id"] in regular_game_ids
    ]
    team_toi = Counter()  # (game, team) -> seconds all of the team's goalies played
    for row in goalie_rows:
        team_toi[(row["game_id"], row["team_id"])] += row["toi_seconds"] or 0

    totals = defaultdict(Counter)
    names = {}
    games = defaultdict(set)
    first_dates = {}
    for row in goalie_rows:
        key = (row["player_id"], row["team_id"])
        toi = row["toi_seconds"] or 0
        names[key] = row["name"]
        if toi > 0:
            games[key].add(row["game_id"])
            date = (game_dates or {}).get(row["game_id"])
            if date is not None and (key not in first_dates or date < first_dates[key]):
                first_dates[key] = date
        for column in GOALIE_SUM_COLUMNS:
            value = shots_in(row[column]) if column in SHOTS_BY_STRENGTH else row[column]
            totals[key][column] += value or 0
        totals[key]["games_started"] += 1 if row["starter"] else 0
        if row["decision"] in DECISION_COLUMNS:
            totals[key][DECISION_COLUMNS[row["decision"]]] += 1
        if (row["decision"] in ("W", "O") and toi > 0 and not row["goals_against"]
                and toi == team_toi[(row["game_id"], row["team_id"])]):
            totals[key]["shutouts"] += 1
    rows = []
    for key in sorted(totals):
        player_id, team_id = key
        row = {
            "player_id": player_id,
            "team_id": team_id,
            "name": names[key],
            "position": "G",
            "games_played": len(games[key]),
            "first_game_date": first_dates.get(key),
        }
        row.update({column: totals[key][column] for column in GOALIE_COLUMNS})
        rows.append(row)
    return rows