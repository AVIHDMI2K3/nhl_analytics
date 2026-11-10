"""Phase 4.12: faceoff wins, losses and percentage per skater (pure logic, no file access).

Counted straight from the faceoff events, so every game is included (no shift data needed). A faceoff has a
winner (`winning_player_id`, on the team that owns the event) and a loser. Each of the two skaters gets one
faceoff in these situations:
  all          every faceoff
  ev, pp, sh   his team's strength, from the NHL situationCode on the event (a pulled goalie is an extra
               attacker, not a skater, as in special_teams.py); the loser sees the mirror image
  oz, dz, nz   the zone in his own terms (offensive, defensive, neutral). The event's zone_code is the winner's
               view, so the loser's zone is flipped (offensive <-> defensive)
The percentage is 100 x wins / faceoffs. Checked against the NHL's skater faceoff report with
scripts/check_player_faceoffs.py.
"""

from collections import Counter, defaultdict

from base_tables import strength_from_counts
from onice import parse_situation_code

SITUATIONS = ("all", "ev", "pp", "sh", "oz", "dz", "nz")
COUNT_COLUMNS = ("faceoffs", "faceoff_wins", "faceoff_losses")
RATE_COLUMNS = ("faceoff_pct",)
ZONES = {"O": "oz", "D": "dz", "N": "nz"}
FLIP = {"O": "D", "D": "O", "N": "N"}


def side_strength(code, side):
    """'pp', 'sh' or 'ev' for `side` ('home' or 'away') from a parsed situation code."""
    other = "away" if side == "home" else "home"
    return strength_from_counts(
        code[f"{side}_skaters"], code[f"{side}_goalie"], code[f"{other}_skaters"], code[f"{other}_goalie"]
    )


def count_faceoffs(events, games):
    """({(player_id, team_id, situation): Counter of COUNT_COLUMNS}, {(player_id, team_id): set of game ids},
    number of faceoff events skipped for a missing player, team or game).

    `events` are staging event rows (game_id, event_type, event_owner_team_id, zone_code, situation_code,
    winning_player_id, losing_player_id); `games` is {game_id: row with home_team_id and away_team_id}."""
    totals = defaultdict(Counter)
    played = defaultdict(set)
    skipped = 0
    for event in events:
        if event["event_type"] != "faceoff":
            continue
        game = games.get(event["game_id"])
        winner, loser, owner = event["winning_player_id"], event["losing_player_id"], event["event_owner_team_id"]
        if game is None or winner is None or loser is None or owner not in (game["home_team_id"], game["away_team_id"]):
            skipped += 1
            continue
        home_won = owner == game["home_team_id"]
        other_team = game["away_team_id"] if home_won else game["home_team_id"]
        code = parse_situation_code(event["situation_code"])
        zone = event["zone_code"]
        sides = (("home", "away") if home_won else ("away", "home"))
        for player, team, side, player_zone, won in (
            (winner, owner, sides[0], zone, True), (loser, other_team, sides[1], FLIP.get(zone), False),
        ):
            situations = ["all"]
            if code is not None:
                situations.append(side_strength(code, side))
            if player_zone in ZONES:
                situations.append(ZONES[player_zone])
            played[(player, team)].add(event["game_id"])
            for situation in situations:
                counts = totals[(player, team, situation)]
                counts["faceoffs"] += 1
                counts["faceoff_wins" if won else "faceoff_losses"] += 1
    return totals, {key: len(value) for key, value in played.items()}, skipped


def add_faceoff_rates(row):
    row["faceoff_pct"] = 100 * row["faceoff_wins"] / row["faceoffs"] if row["faceoffs"] else None
    return row