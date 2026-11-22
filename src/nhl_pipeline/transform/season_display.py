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

from season_totals import GOALIE_COLUMNS, SUM_COLUMNS

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
GOALIE_RATE_COLUMNS = [
    "toi_per_game_seconds",
    "save_pct",
    "even_strength_save_pct",
    "power_play_save_pct",
    "shorthanded_save_pct",
    "goals_against_avg",
    "shots_against_per_60",
]
STRENGTH_SAVE_PCT = {  # rate -> the strength's shots and goals against
    "even_strength_save_pct": ("even_strength_shots_against", "even_strength_goals_against"),
    "power_play_save_pct": ("power_play_shots_against", "power_play_goals_against"),
    "shorthanded_save_pct": ("shorthanded_shots_against", "shorthanded_goals_against"),
}
TOTAL_TEAM = "TOT"


def add_rates(row):
    toi = row["toi_seconds"]
    row["toi_per_game_seconds"] = toi / row["games_played"] if row["games_played"] else None
    row["shooting_pct"] = 100 * row["goals"] / row["sog"] if row["sog"] else None
    for rate, column in PER_60.items():
        row[rate] = row[column] * 3600 / toi if toi else None
    return row


def add_goalie_rates(row):
    """Save percentages are 0-100 like shooting_pct. Goals-against average is per 60 minutes."""
    toi, shots = row["toi_seconds"], row["shots_against"]
    row["toi_per_game_seconds"] = toi / row["games_played"] if row["games_played"] else None
    row["save_pct"] = 100 * row["saves"] / shots if shots else None
    for rate, (shots_column, goals_column) in STRENGTH_SAVE_PCT.items():
        strength_shots = row[shots_column]
        row[rate] = 100 * (strength_shots - row[goals_column]) / strength_shots if strength_shots else None
    row["goals_against_avg"] = row["goals_against"] * 3600 / toi if toi else None
    row["shots_against_per_60"] = shots * 3600 / toi if toi else None
    return row


def build_goalie_display(totals, names, team_abbrevs):
    """Display rows from goalie_season_totals rows, combined like the skaters' (see build_season_display)."""
    return build_season_display(totals, names, team_abbrevs, GOALIE_COLUMNS, add_goalie_rates)


def build_season_display(totals, names, team_abbrevs, sum_columns=SUM_COLUMNS, add_rates_to=add_rates):
    """Display rows from player_season_totals rows (or goalie_season_totals rows, see build_goalie_display).

    `names` maps player id to a full name (the boxscore's short name is used if missing) and
    `team_abbrevs` maps team id to its abbreviation. `sum_columns` are the totals that are added up
    on the combined row, `add_rates_to` works out the rates of a row.
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
                "player_id": player_id,
                "name": name,
                "position": row["position"],
                "kind": "team",
                "team_id": row["team_id"],
                "team": abbrev,
                "teams": ", ".join(abbrevs),
                "games_played": row["games_played"],
            }
            shown.update({column: row[column] for column in sum_columns})
            team_rows.append(add_rates_to(shown))
        if len(team_rows) > 1:
            combined = {
                "player_id": player_id,
                "name": name,
                "position": max(team_rows, key=lambda r: r["games_played"])["position"],
                "kind": "total",
                "team_id": None,
                "team": TOTAL_TEAM,
                "teams": ", ".join(abbrevs),
                "games_played": sum(r["games_played"] for r in team_rows),
            }
            combined.update({column: sum(r[column] for r in team_rows) for column in sum_columns})
            out.append(add_rates_to(combined))
        out.extend(team_rows)
    return out
