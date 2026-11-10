"""Compare power-play opportunities per team and game with the NHL's, and find what the differences share.

Run from the repo root with the `nhl` conda environment active, after ingest_reference.py (the per-game
reports team_powerplay_games and team_penaltykill_games):

    python scripts/diagnose_team_opportunities_by_game.py --season 2025

For every team and game, our count (from the penalty events, see diagnose_team_opportunities.py) is
compared with the NHL's ppOpportunities (power-play report) and timesShorthanded (penalty-kill report).
It prints how often each variant is exact and how far off it is when not, then, for the plain offset
count, a table of features of the game (a 4-minute penalty, a major, a bench minor, two penalties to one
team at the same second, a penalty during an existing penalty...) with how many of the team-games having
the feature disagree. A feature whose team-games nearly all disagree points at the missing rule. Finally it
lists the first games that disagree, with their penalties.
"""

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from diagnose_team_opportunities import (  # noqa: E402
    COUNTED_MINUTES, count_opportunities, count_opportunities_clock,
)

RAW_ROOT = REPO_ROOT / "data" / "raw"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
# (label, counting function, options)
BASE = {"offset": True, "split_double_minors": True, "ignore_end": "no_overtime"}
VARIANTS = (
    ("offset", count_opportunities, {"offset": True}),
    ("double minors split, none at 3600 s unless overtime follows", count_opportunities, BASE),
    ("... and a minor does not count against a major", count_opportunities, {**BASE, "minor_vs_major": True}),
    ("... and none in the last 10 s of regulation", count_opportunities, {**BASE, "late_seconds": 10}),
    ("... and none in the last 20 s", count_opportunities, {**BASE, "late_seconds": 20}),
    ("... and none in the last 30 s", count_opportunities, {**BASE, "late_seconds": 30}),
    ("... and none in the last 60 s", count_opportunities, {**BASE, "late_seconds": 60}),
    ("... minor vs major, none in the last 20 s", count_opportunities,
     {**BASE, "minor_vs_major": True, "late_seconds": 20}),
    ("... minor vs major, none in the last 30 s", count_opportunities,
     {**BASE, "minor_vs_major": True, "late_seconds": 30}),
    ("... minor vs major, none in the last 60 s", count_opportunities,
     {**BASE, "minor_vs_major": True, "late_seconds": 60}),
)


def by_game(penalties):
    groups = defaultdict(list)
    for row in penalties:
        groups[row["game_id"]].append(row)
    return groups


def per_game_counts(penalties, counter=count_opportunities, **options):
    """({(game_id, team_id): opportunities}, {(game_id, team_id): times shorthanded}) for every team that
    has a counted penalty in the game."""
    opportunities, shorthanded = {}, {}
    for game_id, rows in by_game(penalties).items():
        opp, short = counter(rows, **options)
        for team, n in opp.items():
            opportunities[(game_id, team)] = n
        for team, n in short.items():
            shorthanded[(game_id, team)] = n
    return opportunities, shorthanded


def compare(ours, nhl):
    """(exact, total, Counter of ours minus NHL) over the NHL's team-games; a missing count is 0."""
    diffs = Counter(ours.get(key, 0) - value for key, value in nhl.items())
    return diffs[0], len(nhl), diffs


def game_features(rows, team):
    """Features of one game's penalties for a team, as a set of names. `rows` are the game's penalty rows;
    `team` is the team whose opportunities (penalties by the opponent) are being counted."""
    counted = [r for r in rows if r["penalty_minutes"] in COUNTED_MINUTES]
    theirs = [r for r in counted if r["event_owner_team_id"] != team]  # penalties that give `team` a power play
    mine = [r for r in counted if r["event_owner_team_id"] == team]
    features = set()
    if any(r["penalty_minutes"] == 4 for r in theirs):
        features.add("opponent double minor (4 min)")
    if any(r["penalty_minutes"] == 5 for r in theirs):
        features.add("opponent major")
    if any(r.get("penalty_type_code") == "BEN" for r in theirs):
        features.add("opponent bench minor")
    if any(r["penalty_minutes"] == 5 for r in mine):
        features.add("own major")
    seconds = Counter(r["game_seconds"] for r in theirs)
    if any(n > 1 for n in seconds.values()):
        features.add("two opponent penalties at the same second")
    if any(r["game_seconds"] in {m["game_seconds"] for m in mine} for r in theirs):
        features.add("both teams penalized at the same second")
    ordered = sorted(r["game_seconds"] for r in theirs)
    if any(b - a <= 120 for a, b in zip(ordered, ordered[1:])):
        features.add("opponent penalties within 2 minutes of each other")
    if any(r["penalty_minutes"] in (10, 0) or r.get("penalty_type_code") in ("MIS", "GAM", "PS") for r in rows):
        features.add("misconduct or penalty shot in the game")
    if any(r["period_type"] == "OT" for r in counted):
        features.add("overtime penalty")
    return features


def feature_table(nhl, ours, penalties_by_game):
    """{feature: (team-games with it, team-games with it that disagree)}; also 'all' and 'none'."""
    table = defaultdict(lambda: [0, 0])
    for (game_id, team), value in nhl.items():
        features = game_features(penalties_by_game.get(game_id, []), team) or {"none of these"}
        bad = ours.get((game_id, team), 0) != value
        for name in features | {"all team-games"}:
            table[name][0] += 1
            table[name][1] += bad
    return table


def load_games(season, name):
    path = RAW_ROOT / f"season={season}" / "reference" / f"{name}.json.gz"
    with gzip.open(path, "rb") as handle:
        data = json.loads(handle.read())["data"]
    if data and not {"gameId", "teamId"} <= set(data[0]):
        sys.exit(f"{name} has no gameId and teamId; its fields are {sorted(data[0])}")
    return data


def main():
    parser = argparse.ArgumentParser(description="Compare opportunities per game with the NHL's.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--show", type=int, default=12, help="how many disagreeing games to list")
    args = parser.parse_args()
    import pyarrow.parquet as pq

    path = STAGING_ROOT / f"season={args.season}" / "events.parquet"
    columns = pq.ParquetFile(path).schema_arrow.names
    wanted = ["game_id", "event_type", "period_type", "game_seconds", "event_owner_team_id", "penalty_minutes",
              "penalty_type_code", "penalty_desc_key"]
    events = pq.read_table(path, columns=[c for c in wanted if c in columns]).to_pylist()
    games = {g["game_id"]: g for g in pq.read_table(
        STAGING_ROOT / f"season={args.season}" / "games.parquet",
        columns=["game_id", "home_team_id", "away_team_id"]).to_pylist()}
    overtime_games = {e["game_id"] for e in events if e["period_type"] == "OT"}
    penalties = []
    for event in events:
        if event["event_type"] == "penalty":
            event["game_has_ot"] = event["game_id"] in overtime_games
            game = games[event["game_id"]]
            owner = event["event_owner_team_id"]
            event["opponent_team_id"] = game["away_team_id"] if owner == game["home_team_id"] else game["home_team_id"]
            penalties.append(event)
    penalties_by_game = by_game(penalties)

    power = load_games(args.season, "team_powerplay_games")
    kill = load_games(args.season, "team_penaltykill_games")
    print(f"Season {args.season}: per-game fields (power play): {sorted(power[0])}")
    nhl_opp = {(r["gameId"], r["teamId"]): r["ppOpportunities"] for r in power}
    nhl_short = {(r["gameId"], r["teamId"]): r["timesShorthanded"] for r in kill}
    print(f"team-games: {len(nhl_opp)} (power play), {len(nhl_short)} (penalty kill); "
          f"NHL totals {sum(nhl_opp.values())} and {sum(nhl_short.values())}")

    results, exact = {}, {}
    for label, counter, options in VARIANTS:
        opp, short = per_game_counts(penalties, counter=counter, **options)
        a, b = compare(opp, nhl_opp), compare(short, nhl_short)
        results[label], exact[label] = (opp, short), a[0] + b[0]
        print(f"\n{label}: opportunities exact in {a[0]} of {a[1]} team-games, times shorthanded in {b[0]} of {b[1]}"
              f" (NHL total {sum(nhl_opp.values())}, ours {sum(opp.values())})")
        print(f"  opportunities, ours minus NHL: {dict(sorted(a[2].items()))}")

    best = max(exact, key=exact.get)
    opp, _ = results[best]
    print(f"\n'{best}': team-games with a feature, and how many of them disagree with the NHL")
    for name, (n, bad) in sorted(feature_table(nhl_opp, opp, penalties_by_game).items(), key=lambda kv: -kv[1][1]):
        print(f"  {name:48s} {n:5d} team-games, {bad:4d} disagree ({100 * bad / n:5.1f}%)")

    print(f"\nFirst {args.show} disagreeing team-games (ours / NHL opportunities), with the game's penalties:")
    shown = 0
    for (game_id, team), value in sorted(nhl_opp.items()):
        if shown >= args.show:
            break
        if opp.get((game_id, team), 0) == value:
            continue
        shown += 1
        print(f"  game {game_id} team {team}: ours {opp.get((game_id, team), 0)} NHL {value}")
        for r in sorted(penalties_by_game.get(game_id, []), key=lambda r: r["game_seconds"]):
            print(f"      {r['game_seconds']:5d}s  {'this team' if r['event_owner_team_id'] == team else 'opponent':9s} "
                  f"{r['penalty_minutes']:>2} min {r.get('penalty_type_code')}  {r.get('penalty_desc_key')}")


if __name__ == "__main__":
    main()