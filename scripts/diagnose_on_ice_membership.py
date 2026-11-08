"""Test whether the remaining on-ice goal differences are about WHO was on the ice at a line change.

Run from the repo root with the `nhl` conda environment active, after build_base_tables.py and
ingest_reference.py:

    python scripts/diagnose_on_ice_membership.py --season 2025

The NHL's power-play report has goals for per 60 and the penalty-kill report goals against per 60, each
with the skater's time on ice. From them we get the NHL's on-ice goals for each skater (per 60 x seconds
/ 3600, rounded). We compare with ours, goal by goal rebuilt from the stints and the situation code, and
ask, for each skater whose number differs, whether it could be closed by moving goals scored at a line
change onto or off him:

  possible_extra  goals he was NOT credited with but could have been: he was on the ice in a stint that
                  ends or starts within `window` seconds of the goal
  possible_lost   goals he WAS credited with but was not on the ice in every such stint

A skater with ours below the NHL is "explained" if possible_extra >= the gap; with ours above, if
possible_lost >= the gap. Skaters with no goals at a line change that can move are "not explained", and
point to another cause (the NHL's own attribution, penalty timing, a different rule).
Run for window 0 (the stint ending at the goal second against the one starting at it) and window 1.
In 2024 only the skaters with shift data in every game are compared (the NHL's goals include the 57
games without shifts).
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from base_tables import strength_from_counts  # noqa: E402
from stints import StintIndex  # noqa: E402

SIDES = ("home", "away")
# NHL per-60 field -> (situation, our on-ice key, report name, seconds field)
FIELDS = {
    "pp": ("ppGoalsForPer60", "gf", "skater_powerplay", "ppTimeOnIce"),
    "sh": ("ppGoalsAgainstPer60", "ga", "skater_penaltykill", "shTimeOnIce"),
}


def candidate_stints(index, time, window):
    """The stint the goal belongs to (ending at its second) and the stints that end or start within
    `window` seconds of it."""
    current = index.at(time, end_inclusive=True)
    found = []
    for step in range(-window, window + 1):
        for end_inclusive in (True, False):
            stint = index.at(time + step, end_inclusive=end_inclusive)
            if stint is not None and not any(stint is other for other in found):
                found.append(stint)
    return current, found


def membership_counts(stints_by_game, goals, window=0):
    """{(player_id, situation): Counter(ours, extra, lost)}.

    `stints_by_game` {game_id: stint rows sorted by start} (home_skater_ids, away_skater_ids,
    start_game_seconds, end_game_seconds); `goals` shot_attempts rows of goals (game_id, game_seconds,
    is_home, skaters_for, skaters_against, goalie_for, goalie_against). Power-play goals count for the
    scoring side's skaters ('pp', key gf), and against the skaters of the shorthanded side ('sh', key ga).
    """
    indexes = {game_id: StintIndex(rows) for game_id, rows in stints_by_game.items()}
    counts = defaultdict(Counter)
    for goal in goals:
        index = indexes.get(goal["game_id"])
        if index is None:
            continue
        current, found = candidate_stints(index, goal["game_seconds"], window)
        if current is None:
            continue
        shooting = "home" if goal["is_home"] else "away"
        if strength_from_counts(goal["skaters_for"], goal["goalie_for"],
                                goal["skaters_against"], goal["goalie_against"]) != "pp":
            continue
        for side, situation in ((shooting, "pp"), (SIDES[1 - SIDES.index(shooting)], "sh")):
            key = f"{side}_skater_ids"
            sets = [set(stint[key]) for stint in found]
            on_now = set(current[key])
            union, inter = set().union(*sets), set.intersection(*sets)
            for player in on_now:
                counts[(player, situation)]["ours"] += 1
            for player in union - on_now:
                counts[(player, situation)]["extra"] += 1
            for player in on_now - inter:
                counts[(player, situation)]["lost"] += 1
    return counts


def explain(counts, reference, situation, players):
    """Summary dict for one situation. `reference` {player_id: NHL report row}."""
    field, _, _, seconds_field = FIELDS[situation]
    out = Counter()
    for player in players:
        row = reference[player]
        seconds, per60 = row.get(seconds_field) or 0, row.get(field)
        if not seconds or per60 is None:
            continue
        nhl = round(per60 * seconds / 3600)
        c = counts.get((player, situation), Counter())
        gap = c["ours"] - nhl
        out["skaters"] += 1
        if gap == 0:
            out["exact"] += 1
            out["exact_with_line_change_goals"] += bool(c["extra"] or c["lost"])
        else:
            out["differ"] += 1
            movable = c["extra"] if gap < 0 else c["lost"]
            out["explained"] += movable >= abs(gap)
            out["none_movable"] += movable == 0
            out["gap_total"] += gap
    return out


def main():
    parser = argparse.ArgumentParser(description="Test whether on-ice goal differences come from line changes.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    import pyarrow.parquet as pq
    from check_player_special_teams import load_report, skaters_with_all_games, special_team_counts, STATE_COLUMNS

    metrics = REPO_ROOT / "data" / "metrics" / f"season={args.season}"
    stints = defaultdict(list)
    for row in pq.read_table(metrics / "stints.parquet", columns=[
            "game_id", "start_game_seconds", "end_game_seconds", "home_skater_ids", "away_skater_ids"]).to_pylist():
        stints[row["game_id"]].append(row)
    for rows in stints.values():
        rows.sort(key=lambda r: r["start_game_seconds"])
    goals = [r for r in pq.read_table(metrics / "shot_attempts.parquet", columns=[
        "game_id", "game_seconds", "attempt_type", "is_home", "skaters_for", "skaters_against",
        "goalie_for", "goalie_against"]).to_pylist() if r["attempt_type"] == "goal"]
    table = special_team_counts(pq.read_table(metrics / "player_game_strength.parquet",
                                              columns=STATE_COLUMNS).to_pylist())
    clean = skaters_with_all_games(metrics)

    for situation, (field, key, report, _) in FIELDS.items():
        reference = load_report(args.season, report)
        players = [p for p in reference if p in clean]
        label = "Power play, goals for" if situation == "pp" else "Penalty kill, goals against"
        base = membership_counts(stints, goals, window=0)
        same = sum(1 for p in players if base.get((p, situation), Counter())["ours"] == table.get(p, {}).get(situation, Counter())[key])
        print(f"\nSeason {args.season} {label} ({len(players)} skaters with shift data in every game); "
              f"our rebuilt count equals the built table's for {same} of them")
        for window in (0, 1):
            counts = membership_counts(stints, goals, window=window)
            s = explain(counts, reference, situation, players)
            print(f"  window {window}s: {s['exact']} of {s['skaters']} match the NHL's goals; "
                  f"{s['differ']} differ (sum of gaps {s['gap_total']:+d}): "
                  f"{s['explained']} could be closed by line-change goals, "
                  f"{s['differ'] - s['explained']} could not ({s['none_movable']} of those have no movable goal at all); "
                  f"matching skaters that also had line-change goals: {s['exact_with_line_change_goals']}")


if __name__ == "__main__":
    main()