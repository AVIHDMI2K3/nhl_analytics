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
"""

from collections import Counter, defaultdict

SUM_COLUMNS = (
    "goals", "assists", "points", "plus_minus", "pim", "hits", "power_play_goals",
    "sog", "blocked_shots", "giveaways", "takeaways", "toi_seconds", "shifts",
)
REGULAR_SEASON = 2


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