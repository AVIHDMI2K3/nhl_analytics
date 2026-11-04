"""Phase 4.6: the fan-facing season table for skaters (pure logic).

Built from player_season_totals (the boxscore totals, season_totals.py). One row per player
and team, in order of when he joined the team, plus one combined row for a player who played
for more than one team that season, so the app can show "all teams" or each team on its own.

  kind   'total' (all his teams added together) or 'team' (one team)
  team   the team's abbreviation; 'TOT' on a combined row
  teams  every team he played for, in order, e.g. 'SJS, VGK'

Every rate is worked out on the row it sits on, from that row's own totals, never by
averaging other rates. Rates that need time on ice use the boxscore's time on ice, which comes
from the same games as the counts. A rate is None when its divisor is zero.
"""

from collections import defaultdict

from season_totals import SUM_COLUMNS

PER_60 = {
    "goals_per_60": "goals",
    "assists_per_60": "assists",
    "points_per_60": "points",
    "shots_per_60": "sog",
    "hits_per_60": "hits",
    "blocks_per_60": "blocked_shots",
    "giveaways_per_60": "giveaways",
    "takeaways_per_60": "takeaways",
}
RATE_COLUMNS = ["toi_per_game_seconds", "shooting_pct"] + list(PER_60)
TOTAL_TEAM = "TOT"


def add_rates(row):
    toi = row["toi_seconds"]
    row["toi_per_game_seconds"] = toi / row["games_played"] if row["games_played"] else None
    row["shooting_pct"] = 100 * row["goals"] / row["sog"] if row["sog"] else None
    for rate, column in PER_60.items():
        row[rate] = row[column] * 3600 / toi if toi else None
    return row


def build_season_display(totals, names, team_abbrevs):
    """Display rows from player_season_totals rows.

    `names` maps player id to a full name (the boxscore's short name is used if missing) and
    `team_abbrevs` maps team id to its abbreviation.
    """
    by_player = defaultdict(list)
    for row in totals:
        by_player[row["player_id"]].append(row)

    out = []
    for player_id in sorted(by_player):
        # order teams by when he joined them; a missing date sorts last
        teams = sorted(by_player[player_id], key=lambda r: (r["first_game_date"] or "9999", r["team_id"]))
        name = names.get(player_id) or teams[0]["name"]
        abbrevs = [team_abbrevs.get(r["team_id"], str(r["team_id"])) for r in teams]
        team_rows = []
        for row, abbrev in zip(teams, abbrevs):
            shown = {
                "player_id": player_id, "name": name, "position": row["position"], "kind": "team",
                "team_id": row["team_id"], "team": abbrev, "teams": ", ".join(abbrevs),
                "games_played": row["games_played"],
            }
            shown.update({column: row[column] for column in SUM_COLUMNS})
            team_rows.append(add_rates(shown))
        if len(team_rows) > 1:
            combined = {
                "player_id": player_id, "name": name,
                "position": max(team_rows, key=lambda r: r["games_played"])["position"],
                "kind": "total", "team_id": None, "team": TOTAL_TEAM, "teams": ", ".join(abbrevs),
                "games_played": sum(r["games_played"] for r in team_rows),
            }
            combined.update({column: sum(r[column] for r in team_rows) for column in SUM_COLUMNS})
            out.append(add_rates(combined))
        out.extend(team_rows)
    return out