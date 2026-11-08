"""Phase 4.7: advanced on-ice stats per skater and season (pure logic).

Built from the long base tables (base_tables.py): player_game_strength and team_game_strength.
Only games with shift data are in them, so these stats cover those games.

A situation is a group of states that fans ask for:
  all  every state             ev   even strength (includes 4v4, 3v3 and empty net)
  5v5  five skaters and a goalie each side, no empty net
  pp   power play              sh   shorthanded

For each player, team and situation we add up, over the season:
  on ice   seconds, and attempts for and against while he was on the ice
             cf/ca  Corsi (goals, shots on goal, misses and blocks)
             ff/fa  Fenwick (goals, shots on goal and misses)
             sf/sa  shots on goal (goals and shots on goal)
             gf/ga  goals
  his own  icf, iff, isf, ig (the same kinds of attempt, taken by him) and blocks_made
  off ice  the same on-ice counts for his team in the games he played, minus his own. These are
           the team's numbers while he was not on the ice, in games he played in.
Percentages and per-60 rates are worked out from the sums, never by averaging rates. A rate is
None when its divisor is zero. 'rel' is the on-ice percentage minus the off-ice percentage.
"""

from collections import Counter, defaultdict

from base_tables import KINDS

SITUATIONS = ("all", "ev", "5v5", "pp", "sh")
ON_ICE = ("seconds", "cf", "ca", "ff", "fa", "sf", "sa", "gf", "ga")
INDIVIDUAL = ("icf", "iff", "isf", "ig", "blocks_made")
OFF_ICE = tuple(f"off_{column}" for column in ON_ICE)
COUNT_COLUMNS = ON_ICE + INDIVIDUAL + OFF_ICE
AGAINST = {"cf": "ca", "ff": "fa", "sf": "sa", "gf": "ga"}
PERCENT_COLUMNS = [f"{name}_pct" for name in AGAINST] + [f"{name}_pct_rel" for name in AGAINST]
PER_60_SOURCES = ("cf", "ca", "ff", "fa", "sf", "sa", "gf", "ga", "icf", "isf", "ig", "blocks_made")
RATE_COLUMNS = PERCENT_COLUMNS + [f"{name}_per_60" for name in PER_60_SOURCES]


def situations_of(row):
    """The situations a state row belongs to."""
    found = ["all"]
    strength = row["strength"]
    if strength == "ev":
        found.append("ev")
        if (row["skaters_for"], row["skaters_against"], row["goalies_for"], row["goalies_against"]) == (5, 5, 1, 1):
            found.append("5v5")
    else:
        found.append(strength)
    return found


def attempt_counts(row, prefix):
    goal, sog, miss, block = (row[f"{prefix}_{kind}"] for kind in KINDS)
    return goal + sog + miss + block, goal + sog + miss, goal + sog, goal


def counts_of(row, individual):
    """On-ice counts of one state row, plus the player's own when `individual`."""
    cf, ff, sf, gf = attempt_counts(row, "for")
    ca, fa, sa, ga = attempt_counts(row, "against")
    counts = {"seconds": row["seconds"], "cf": cf, "ca": ca, "ff": ff, "fa": fa, "sf": sf, "sa": sa, "gf": gf, "ga": ga}
    if individual:
        icf, iff, isf, ig = attempt_counts(row, "ind")
        counts.update({"icf": icf, "iff": iff, "isf": isf, "ig": ig, "blocks_made": row["blocks_made"]})
    return counts


def build_advanced_counts(player_rows, team_rows):
    """({(player_id, team_id, situation): Counter of COUNT_COLUMNS}, {(player_id, team_id): games}).

    Off-ice counts are, game by game, the team's counts in the situation minus the player's.
    """
    team_game = defaultdict(Counter)
    for row in team_rows:
        counts = counts_of(row, False)
        for situation in situations_of(row):
            team_game[(row["game_id"], row["team_id"], situation)].update(counts)

    player_game = defaultdict(Counter)
    games = defaultdict(set)
    for row in player_rows:
        games[(row["player_id"], row["team_id"])].add(row["game_id"])
        counts = counts_of(row, True)
        for situation in situations_of(row):
            player_game[(row["game_id"], row["player_id"], row["team_id"], situation)].update(counts)

    totals = defaultdict(Counter)
    for (game_id, player_id, team_id, situation), counts in player_game.items():
        total = totals[(player_id, team_id, situation)]
        total.update(counts)
        team = team_game[(game_id, team_id, situation)]
        for column in ON_ICE:
            total[f"off_{column}"] += team[column] - counts[column]
    return totals, {key: len(value) for key, value in games.items()}


def percent(for_count, against_count):
    both = for_count + against_count
    return 100 * for_count / both if both else None


def add_rates(row):
    for name, against in AGAINST.items():
        row[f"{name}_pct"] = percent(row[name], row[against])
        off = percent(row[f"off_{name}"], row[f"off_{against}"])
        row[f"{name}_pct_rel"] = None if row[f"{name}_pct"] is None or off is None else row[f"{name}_pct"] - off
    for name in PER_60_SOURCES:
        row[f"{name}_per_60"] = row[name] * 3600 / row["seconds"] if row["seconds"] else None
    return row


def build_advanced_display(totals, games, season_rows, names, team_abbrevs,
                           situations=SITUATIONS, columns=COUNT_COLUMNS, add_rates_to=add_rates):
    """Fan-facing rows: one per player, team (or combined) and situation.

    `situations`, `columns` and `add_rates_to` default to the advanced on-ice ones; special_teams.py
    passes its own to get the same layout (traded players, games played and included) for its table.

    `season_rows` are player_season_totals rows (identity, boxscore games played, the date he
    joined each team). A traded player gets a combined row per situation, then one per team in
    the order he joined them, as in season_display.py. games_played is the boxscore's;
    games_included is the number of games with shift data that the on-ice numbers cover.
    """
    by_player = defaultdict(list)
    for row in season_rows:
        by_player[row["player_id"]].append(row)

    out = []
    for player_id in sorted(by_player):
        teams = sorted(by_player[player_id], key=lambda r: (r["first_game_date"] or "9999", r["team_id"]))
        name = names.get(player_id) or teams[0]["name"]
        abbrevs = [team_abbrevs.get(r["team_id"], str(r["team_id"])) for r in teams]
        team_rows = []
        for row, abbrev in zip(teams, abbrevs):
            for situation in situations:
                counts = totals.get((player_id, row["team_id"], situation))
                if counts is None:
                    continue
                shown = {
                    "player_id": player_id, "name": name, "position": row["position"], "kind": "team",
                    "team_id": row["team_id"], "team": abbrev, "teams": ", ".join(abbrevs), "situation": situation,
                    "games_played": row["games_played"], "games_included": games[(player_id, row["team_id"])],
                }
                shown.update({column: counts[column] for column in columns})
                team_rows.append(add_rates_to(shown))
        if len({r["team_id"] for r in team_rows}) > 1:
            for situation in situations:
                parts = [r for r in team_rows if r["situation"] == situation]
                if not parts:
                    continue
                combined = {
                    "player_id": player_id, "name": name,
                    "position": max(teams, key=lambda r: r["games_played"])["position"],
                    "kind": "total", "team_id": None, "team": "TOT", "teams": ", ".join(abbrevs),
                    "situation": situation,
                    "games_played": sum(r["games_played"] for r in teams),
                    "games_included": sum(games[(player_id, r["team_id"])] for r in teams if (player_id, r["team_id"]) in games),
                }
                combined.update({column: sum(r[column] for r in parts) for column in columns})
                out.append(add_rates_to(combined))
        out.extend(team_rows)
    return out


TEAM_RATE_COLUMNS = [f"{name}_pct" for name in AGAINST] + [f"{name}_per_60" for name in ON_ICE[1:]]


def build_team_advanced_counts(team_rows):
    """({(team_id, situation): Counter of ON_ICE columns}, {team_id: number of games})."""
    totals = defaultdict(Counter)
    games = defaultdict(set)
    for row in team_rows:
        games[row["team_id"]].add(row["game_id"])
        counts = counts_of(row, False)
        for situation in situations_of(row):
            totals[(row["team_id"], situation)].update(counts)
    return totals, {team_id: len(value) for team_id, value in games.items()}


def add_team_rates(row):
    for name, against in AGAINST.items():
        row[f"{name}_pct"] = percent(row[name], row[against])
    for name in ON_ICE[1:]:
        row[f"{name}_per_60"] = row[name] * 3600 / row["seconds"] if row["seconds"] else None
    return row


def build_team_advanced_display(totals, games, games_played, team_abbrevs):
    """One row per team and situation. `games_played` maps team id to the games it played
    (boxscore games); games_included is the games with shift data that the counts cover."""
    out = []
    for team_id in sorted(games):
        for situation in SITUATIONS:
            counts = totals.get((team_id, situation))
            if counts is None:
                continue
            row = {
                "team_id": team_id, "team": team_abbrevs.get(team_id, str(team_id)), "situation": situation,
                "games_played": games_played.get(team_id), "games_included": games[team_id],
            }
            row.update({column: counts[column] for column in ON_ICE})
            out.append(add_team_rates(row))
    return out