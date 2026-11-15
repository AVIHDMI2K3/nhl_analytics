"""Why do our 5v5 team numbers differ a little from Natural Stat Trick's? (Phase 5)

Run from the repo root with the `nhl` conda environment active, after build_stints.py, with the NST team
5v5 file in place (see check_against_nst.py):

    python scripts/diagnose_nst_5v5.py --season 2023 --folder data/reference/nst

Counts every team's 5v5 Corsi, Fenwick, shots and goals for and against two ways: with the state of each
attempt taken from the NHL situationCode (what the tables do now) and from the shift-based stint, and prints
both beside NST's, so we can see which one NST follows. Also prints our 5v5 time from the stints beside
NST's, and lists the attempts that are 5v5 under one rule and not the other, with the code and the stint's
skaters and goalies, to show what kind of moment they are.
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

from base_tables import KIND_BY_ATTEMPT, code_states  # noqa: E402
from check_against_nst import TEAM_NAMES, normalize_name, number, read_nst  # noqa: E402
from stints import StintIndex, other_side, side_state  # noqa: E402

METRICS_ROOT = REPO_ROOT / "data" / "metrics"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
FIVE_ON_FIVE = ("ev", 5, 5, 1, 1)
ATTEMPT_COLUMNS = ["game_id", "game_seconds", "attempt_type", "team_id", "opponent_team_id", "is_home",
                   "skaters_for", "skaters_against", "goalie_for", "goalie_against"]
STAT_KINDS = {"cf": ("goal", "sog", "miss", "block"), "ff": ("goal", "sog", "miss"), "sf": ("goal", "sog"), "gf": ("goal",)}


def is_five_on_five(state):
    return state is not None and tuple(state) == FIVE_ON_FIVE


AGAINST_NAME = {"cf": "ca", "ff": "fa", "sf": "sa", "gf": "ga"}


def add_attempt(counts, shooting_team, defending_team, kind):
    """Add one attempt of `kind` to the for/against counts of the two teams."""
    for name, kinds in STAT_KINDS.items():
        if kind in kinds:
            counts[(shooting_team, name)] += 1
            counts[(defending_team, AGAINST_NAME[name])] += 1


def classify(attempt, stint):
    """(state under the code or None, state under the stint) for the shooting side."""
    side = "home" if attempt["is_home"] else "away"
    stint_state = side_state(stint, side)
    from_code = code_states(attempt)
    return (None if from_code is None else from_code[0]), stint_state


def count_five_on_five(attempts, stints_by_game):
    """({'code': Counter, 'stint': Counter}, [attempts that differ]) with counts keyed (team_id, stat), stat one of
    cf, ca, ff, fa, sf, sa, gf, ga. Attempts without code counts use the stint's state for both."""
    counts = {"code": Counter(), "stint": Counter()}
    differing = []
    indexes = {game_id: StintIndex(rows) for game_id, rows in stints_by_game.items()}
    for attempt in attempts:
        kind = KIND_BY_ATTEMPT.get(attempt["attempt_type"])
        index = indexes.get(attempt["game_id"])
        if kind is None or index is None:
            continue
        stint = index.at(attempt["game_seconds"], end_inclusive=kind == "goal")
        if stint is None:
            continue
        code_state, stint_state = classify(attempt, stint)
        by_code = is_five_on_five(stint_state if code_state is None else code_state)
        by_stint = is_five_on_five(stint_state)
        if by_code:
            add_attempt(counts["code"], attempt["team_id"], attempt["opponent_team_id"], kind)
        if by_stint:
            add_attempt(counts["stint"], attempt["team_id"], attempt["opponent_team_id"], kind)
        if by_code != by_stint:
            differing.append({"attempt": attempt, "stint": stint, "by_code": by_code, "by_stint": by_stint,
                              "code_state": code_state, "stint_state": stint_state})
    return counts, differing


def five_on_five_minutes(stints_by_game, team_ids_by_game):
    """{team_id: minutes of 5v5 (five skaters and a goalie each) from the stints}."""
    seconds = Counter()
    for game_id, rows in stints_by_game.items():
        teams = team_ids_by_game[game_id]
        for stint in rows:
            for side in ("home", "away"):
                if side_state(stint, side)[1:] == FIVE_ON_FIVE[1:] and stint[f"{side}_strength"] == "ev":
                    seconds[teams[side]] += stint["seconds"]
    return {team: value / 60 for team, value in seconds.items()}


def main():
    parser = argparse.ArgumentParser(description="Diagnose the 5v5 differences from Natural Stat Trick.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--examples", type=int, default=20)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    from build_season_display import team_abbrevs

    staging = STAGING_ROOT / f"season={args.season}"
    metrics = METRICS_ROOT / f"season={args.season}"
    abbrevs = team_abbrevs(staging)
    games = {g["game_id"]: {"home": g["home_team_id"], "away": g["away_team_id"]} for g in pq.read_table(
        staging / "games.parquet", columns=["game_id", "home_team_id", "away_team_id"]).to_pylist()}
    stints_by_game = defaultdict(list)
    for stint in pq.read_table(metrics / "stints.parquet").to_pylist():
        stints_by_game[stint["game_id"]].append(stint)
    for rows in stints_by_game.values():
        rows.sort(key=lambda r: r["start_game_seconds"])
    attempts = pq.read_table(metrics / "shot_attempts.parquet", columns=ATTEMPT_COLUMNS).to_pylist()

    counts, differing = count_five_on_five(attempts, stints_by_game)
    minutes = five_on_five_minutes(stints_by_game, games)
    nst = {TEAM_NAMES[normalize_name(r["Team"])]: r for r in read_nst(args.folder / f"nst_teams_5v5_{args.season}.csv")}

    print(f"Season {args.season}, 5v5, per team: NST / code state / stint state")
    totals = {name: [0, 0, 0] for name in ("cf", "ca", "ff", "fa", "sf", "sa", "gf", "ga")}
    print(f"  {'team':4s} {'CF':>20s} {'GF':>16s} {'GA':>16s}  5v5 minutes NST / ours")
    for team_id, abbrev in sorted(abbrevs.items(), key=lambda item: item[1]):
        row = nst.get(abbrev)
        if row is None:
            continue
        values = {name: (number(row[name.upper()]), counts["code"][(team_id, name)], counts["stint"][(team_id, name)])
                  for name in totals}
        for name, triple in values.items():
            for i in range(3):
                totals[name][i] += triple[i]
        print(f"  {abbrev:4s} {values['cf'][0]:6.0f}/{values['cf'][1]:5d}/{values['cf'][2]:5d} "
              f"{values['gf'][0]:5.0f}/{values['gf'][1]:4d}/{values['gf'][2]:4d} {values['ga'][0]:5.0f}/{values['ga'][1]:4d}/{values['ga'][2]:4d}"
              f"  {number(row['TOI']):8.1f} / {minutes.get(team_id, 0):8.1f}")
    print("\nLeague totals, NST / code state / stint state:")
    for name, (nst_total, code_total, stint_total) in totals.items():
        print(f"  {name.upper():3s} {nst_total:9.0f} {code_total:9d} {stint_total:9d}   code {code_total - nst_total:+.0f}, stint {stint_total - nst_total:+.0f}")

    only_code = [d for d in differing if d["by_code"]]
    only_stint = [d for d in differing if d["by_stint"]]
    print(f"\nAttempts that are 5v5 under one rule only: {len(only_code)} by the code only, {len(only_stint)} by the stint only")
    for label, items in (("by the code only", only_code), ("by the stint only", only_stint)):
        kinds = Counter(KIND_BY_ATTEMPT[d["attempt"]["attempt_type"]] for d in items)
        print(f"  {label}: {dict(kinds)}")
        for d in items[: args.examples]:
            a, s = d["attempt"], d["stint"]
            print(f"    game {a['game_id']} second {a['game_seconds']:4d} {a['attempt_type']:13s} code counts "
                  f"{a['skaters_for']}v{a['skaters_against']} goalies {a['goalie_for']}/{a['goalie_against']}; stint "
                  f"{s['start_game_seconds']}-{s['end_game_seconds']} state {d['stint_state'][1:]} ({d['stint_state'][0]})")


if __name__ == "__main__":
    main()