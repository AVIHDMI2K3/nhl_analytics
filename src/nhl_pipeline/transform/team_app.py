"""Phase 8: the team table the Teams page shows (pure logic, no file access).

One row per team and season, joining three season tables on (season, team_id):
  team_season_basic            standings, goals, shots per game, hits, blocks, giveaways, takeaways, penalty minutes
  team_season_advanced         the '5v5' row only: shot attempts, goals and their shares
  team_season_special_teams    power-play and penalty-kill counts and percentages
and adding the full team name. Columns are grouped the way the page shows them (standings, goals, shots per game,
physical play, 5v5 play, power play, penalty kill). Every 5v5 column ends in _5v5 so it cannot be mistaken for an
all-situations number.

Rows are ordered by points, then goal difference. A team with no 5v5 row or no special-teams row keeps None in those
columns rather than being dropped.
"""

TEAM_NAMES = {
    "ANA": "Anaheim Ducks",
    "ARI": "Arizona Coyotes",
    "BOS": "Boston Bruins",
    "BUF": "Buffalo Sabres",
    "CAR": "Carolina Hurricanes",
    "CBJ": "Columbus Blue Jackets",
    "CGY": "Calgary Flames",
    "CHI": "Chicago Blackhawks",
    "COL": "Colorado Avalanche",
    "DAL": "Dallas Stars",
    "DET": "Detroit Red Wings",
    "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers",
    "LAK": "Los Angeles Kings",
    "MIN": "Minnesota Wild",
    "MTL": "Montreal Canadiens",
    "NJD": "New Jersey Devils",
    "NSH": "Nashville Predators",
    "NYI": "New York Islanders",
    "NYR": "New York Rangers",
    "OTT": "Ottawa Senators",
    "PHI": "Philadelphia Flyers",
    "PIT": "Pittsburgh Penguins",
    "SEA": "Seattle Kraken",
    "SJS": "San Jose Sharks",
    "STL": "St. Louis Blues",
    "TBL": "Tampa Bay Lightning",
    "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth",
    "VAN": "Vancouver Canucks",
    "VGK": "Vegas Golden Knights",
    "WPG": "Winnipeg Jets",
    "WSH": "Washington Capitals",
}
# Utah's name changed after the 2024 season (coded 2024 is 2024-25).
TEAM_NAME_BY_SEASON = {("UTA", 2024): "Utah Hockey Club", ("UTA", 2023): "Utah Hockey Club"}

BASIC_COLUMNS = (
    "games_played",
    "wins",
    "losses",
    "ot_losses",
    "points",
    "points_pct",
    "regulation_wins",
    "row",
    "goals_for",
    "goals_against",
    "goal_diff",
    "shots_for_per_game",
    "shots_against_per_game",
    "hits",
    "blocked_shots",
    "giveaways",
    "takeaways",
    "pim",
)
ADVANCED_COLUMNS = ("cf", "ca", "cf_pct", "ff", "fa", "ff_pct", "sf", "sa", "sf_pct", "gf", "ga", "gf_pct")
SPECIAL_COLUMNS = (
    "pp_opportunities",
    "pp_goals",
    "pp_pct",
    "times_shorthanded",
    "pk_goals_against",
    "pk_pct",
    "sh_goals_for",
    "sh_goals_against",
)
DECIMALS = {"points_pct": 3, "shots_for_per_game": 1, "shots_against_per_game": 1, "pp_pct": 1, "pk_pct": 1}


def team_name(abbreviation, season):
    return TEAM_NAME_BY_SEASON.get((abbreviation, season)) or TEAM_NAMES.get(abbreviation, abbreviation)


def _rounded(key, value):
    if value is None:
        return None
    decimals = DECIMALS.get(key) if key in DECIMALS else (1 if key.endswith("_pct") else None)
    return round(value, decimals) if decimals is not None else value


def build_team_rows(basic, advanced, special):
    """basic, advanced, special: lists of row dicts from the three season tables. Returns the joined rows."""
    adv = {(r["season"], r["team_id"]): r for r in advanced if r["situation"] == "5v5"}
    spe = {(r["season"], r["team_id"]): r for r in special}
    rows = []
    for b in basic:
        key = (b["season"], b["team_id"])
        a = adv.get(key)
        s = spe.get(key)
        row = {
            "season": b["season"],
            "team_id": b["team_id"],
            "team": b["team"],
            "team_name": team_name(b["team"], b["season"]),
        }
        for col in BASIC_COLUMNS:
            row[col] = _rounded(col, b[col])
        for col in ADVANCED_COLUMNS:
            row[f"{col}_5v5"] = _rounded(col, a[col]) if a else None
        for col in SPECIAL_COLUMNS:
            row[col] = _rounded(col, s[col]) if s else None
        rows.append(row)
    rows.sort(key=lambda r: (-r["points"], -r["goal_diff"], r["team"]))
    return rows
