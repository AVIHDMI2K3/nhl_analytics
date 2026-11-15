"""Which shift-boundary rule reproduces Natural Stat Trick's per-skater Corsi? (Phase 5)

Run from the repo root with the `nhl` conda environment active, with the NST all-situations skater file in place
(see check_against_nst.py):

    python scripts/diagnose_boundary_rules.py --season 2023 --folder data/reference/nst

The previous check showed that skaters with no flagged line-change problem still differ from NST, and that the
differences go both ways (some +12, some -12) while the league total is almost the same. That points to who is
credited at a line change, not how many skaters are counted: a skater who steps off at the second of an attempt
is credited or not depending on the boundary rule. We credit an attempt to a skater if his shift covers its
second, and the rule decides whether the first and last second count:
  start    start <= second < end          end    start < second <= end
  both     start <= second <= end         neither start < second < end
We use `start` for shots, misses and blocks and `end` for goals. A scheme gives a rule to each of four cases:
non-goals for the shooting team's skaters, non-goals for the other team's skaters, goals for the shooting team's
skaters and goals for the other team's. The first run (all four rules for non-goals and goals together) showed
that goals should use `end`, that `end` also fits NST a little better than `start` for non-goals, and that the
two sides of Corsi (CF and CA) prefer different rules. So this runs in two stages, each trying the 16 rule pairs
for the shooting side and the other side: first for non-goals (goals fixed at `end`), then for goals (non-goals
fixed at the best of stage 1). Each scheme's skater Corsi, counted from the cleaned shifts, is compared with NST.
"""

import argparse
import sys
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

from check_against_nst import match_skaters, number, read_nst  # noqa: E402

METRICS_ROOT = REPO_ROOT / "data" / "metrics"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"
RULES = ("start", "end", "both", "neither")
ATTEMPT_TYPES = ("goal", "shot-on-goal", "missed-shot", "blocked-shot")
TYPE_GROUPS = {"shot-on-goal": "sog", "missed-shot": "miss", "blocked-shot": "block"}
NON_GOAL_GROUPS = ("sog", "miss", "block")
CURRENT = ("start", "start", "end", "end")  # non-goals start-inclusive, goals end-inclusive, for both sides


def covered_range(times, start, end, rule):
    """(low, high) indexes into the sorted `times` of the seconds a shift [start, end] covers under `rule`."""
    if rule == "start":
        return bisect_left(times, start), bisect_left(times, end)
    if rule == "end":
        return bisect_right(times, start), bisect_right(times, end)
    if rule == "both":
        return bisect_left(times, start), bisect_right(times, end)
    return bisect_right(times, start), bisect_left(times, end)


def on_ice_by_rule(shifts, times):
    """{rule: {second: {team_id: set of skater ids}}} for the sorted list of seconds `times`.
    `shifts` are dicts with player_id, team_id, start, end (goalies already left out)."""
    result = {rule: defaultdict(lambda: defaultdict(set)) for rule in RULES}
    for shift in shifts:
        for rule in RULES:
            low, high = covered_range(times, shift["start"], shift["end"], rule)
            for second in times[low:high]:
                result[rule][second][shift["team_id"]].add(shift["player_id"])
    return result


def count_corsi(attempts, shifts_by_game, schemes):
    """{scheme: Counter keyed (player_id, 'cf' or 'ca')} over all attempts. A scheme is
    (non-goal rule for the shooting team's skaters, non-goal rule for the other team's, goal rule for the
    shooting team's, goal rule for the other team's)."""
    counts = {scheme: Counter() for scheme in schemes}
    attempts_by_game = defaultdict(list)
    for attempt in attempts:
        if attempt["attempt_type"] in ATTEMPT_TYPES:
            attempts_by_game[attempt["game_id"]].append(attempt)
    for game_id, game_attempts in attempts_by_game.items():
        times = sorted({a["game_seconds"] for a in game_attempts})
        members = on_ice_by_rule(shifts_by_game.get(game_id, []), times)
        for attempt in game_attempts:
            goal = attempt["attempt_type"] == "goal"
            second, team, other = attempt["game_seconds"], attempt["team_id"], attempt["opponent_team_id"]
            for scheme, counter in counts.items():
                rule_for, rule_against = (scheme[2], scheme[3]) if goal else (scheme[0], scheme[1])
                for player in members[rule_for].get(second, {}).get(team, ()):
                    counter[(player, "cf")] += 1
                for player in members[rule_against].get(second, {}).get(other, ()):
                    counter[(player, "ca")] += 1
    return counts


def count_by_type(attempts, shifts_by_game):
    """{(group, stat, rule): Counter of player_id -> count} for the non-goal groups sog, miss and block and for
    each rule: the Corsi for ('cf', the shooting team's skaters) and against ('ca', the other team's) he is
    credited with under that rule. Goals are left out; they use the end-inclusive rule on both sides."""
    counts = defaultdict(Counter)
    attempts_by_game = defaultdict(list)
    for attempt in attempts:
        if attempt["attempt_type"] in TYPE_GROUPS:
            attempts_by_game[attempt["game_id"]].append(attempt)
    for game_id, game_attempts in attempts_by_game.items():
        times = sorted({a["game_seconds"] for a in game_attempts})
        members = on_ice_by_rule(shifts_by_game.get(game_id, []), times)
        for attempt in game_attempts:
            group = TYPE_GROUPS[attempt["attempt_type"]]
            second, team, other = attempt["game_seconds"], attempt["team_id"], attempt["opponent_team_id"]
            for rule in RULES:
                on_ice = members[rule].get(second, {})
                for player in on_ice.get(team, ()):
                    counts[(group, "cf", rule)][player] += 1
                for player in on_ice.get(other, ()):
                    counts[(group, "ca", rule)][player] += 1
    return counts


def goal_counts(attempts, shifts_by_game):
    """{'cf': Counter, 'ca': Counter} of the goals credited with the end-inclusive rule on both sides."""
    counts = {"cf": Counter(), "ca": Counter()}
    goals_by_game = defaultdict(list)
    for attempt in attempts:
        if attempt["attempt_type"] == "goal":
            goals_by_game[attempt["game_id"]].append(attempt)
    for game_id, goals in goals_by_game.items():
        members = on_ice_by_rule(shifts_by_game.get(game_id, []), sorted({g["game_seconds"] for g in goals}))["end"]
        for goal in goals:
            on_ice = members.get(goal["game_seconds"], {})
            counts["cf"].update(on_ice.get(goal["team_id"], ()))
            counts["ca"].update(on_ice.get(goal["opponent_team_id"], ()))
    return counts


def score_stat(counter, nst_by_player, index):
    """(skaters, exact, within 2, within 5, mean absolute gap) of one statistic (index 0 = CF, 1 = CA) against NST."""
    gaps = [abs(counter[player] - values[index]) for player, values in nst_by_player.items()]
    return (len(gaps), sum(g == 0 for g in gaps), sum(g <= 2 for g in gaps), sum(g <= 5 for g in gaps),
            sum(gaps) / len(gaps) if gaps else None)


def best_rules_by_type(by_type, goals, nst_by_player):
    """For CF and for CA, every choice of one rule for each non-goal group, best first:
    {stat: [(score_stat result, (rule for sog, rule for miss, rule for block))]}."""
    results = {}
    for index, stat in enumerate(("cf", "ca")):
        rows = []
        for combo in product(RULES, repeat=len(NON_GOAL_GROUPS)):
            total = Counter(goals[stat])
            for group, rule in zip(NON_GOAL_GROUPS, combo):
                total.update(by_type[(group, stat, rule)])
            rows.append((score_stat(total, nst_by_player, index), combo))
        results[stat] = sorted(rows, key=lambda row: row[0][4])
    return results


def score(counter, nst_by_player):
    """(skaters, CF exact, CA exact, both within 2, mean absolute gap over CF and CA) against {player_id: (CF, CA)}."""
    cf_exact = ca_exact = near = 0
    total_gap = 0.0
    for player, (nst_cf, nst_ca) in nst_by_player.items():
        gap_cf, gap_ca = counter[(player, "cf")] - nst_cf, counter[(player, "ca")] - nst_ca
        cf_exact += gap_cf == 0
        ca_exact += gap_ca == 0
        near += abs(gap_cf) <= 2 and abs(gap_ca) <= 2
        total_gap += abs(gap_cf) + abs(gap_ca)
    n = len(nst_by_player)
    return n, cf_exact, ca_exact, near, total_gap / (2 * n) if n else None


def main():
    parser = argparse.ArgumentParser(description="Find the shift-boundary rule closest to NST's Corsi.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--folder", type=Path, required=True)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    metrics = METRICS_ROOT / f"season={args.season}"
    attempts = pq.read_table(metrics / "shot_attempts.parquet", columns=[
        "game_id", "game_seconds", "attempt_type", "team_id", "opponent_team_id"]).to_pylist()
    shifts_by_game = defaultdict(list)
    for row in pq.read_table(INTERMEDIATE_ROOT / f"season={args.season}" / "shifts_clean.parquet").to_pylist():
        if row.get("is_goalie"):
            continue
        start = row["start"] if "start" in row else row["start_game_seconds"]
        end = row["end"] if "end" in row else row["end_game_seconds"]
        shifts_by_game[row["game_id"]].append(
            {"player_id": row["player_id"], "team_id": row["team_id"], "start": start, "end": end})

    players = pq.read_table(metrics / "player_season_advanced.parquet").to_pylist()
    ours = [r for r in players if r["situation"] == "all" and (r["kind"] == "total" or r["teams"] == r["team"])]
    nst_rows = read_nst(args.folder / f"nst_skaters_all_{args.season}.csv")
    matched, _, _ = match_skaters(nst_rows, ours)
    nst_by_player = {mine["player_id"]: (number(nst_rows[i]["CF"]), number(nst_rows[i]["CA"])) for i, mine in matched.items()}

    def run(schemes, title):
        counts = count_corsi(attempts, shifts_by_game, schemes)
        results = sorted(((score(counter, nst_by_player), scheme) for scheme, counter in counts.items()),
                         key=lambda item: item[0][4])
        print(f"\n{title}")
        print(f"  {'non-goals: shooting/other':26s} {'goals: shooting/other':22s} {'CF exact':>9s} {'CA exact':>9s} "
              f"{'both within 2':>14s} {'mean |gap|':>11s}")
        for (n, cf_exact, ca_exact, near, mean), scheme in results:
            mark = "  <- what we use now" if scheme == CURRENT else ""
            print(f"  {scheme[0] + '/' + scheme[1]:26s} {scheme[2] + '/' + scheme[3]:22s} {cf_exact:9d} {ca_exact:9d} {near:14d} {mean:11.2f}{mark}")
        return results[0][1]

    print(f"Season {args.season}: per-skater Corsi (all situations), {len(nst_by_player)} skaters, from the shifts, against NST")
    best = run([(a, b, "end", "end") for a in RULES for b in RULES], "Stage 1: non-goal rules (goals end/end)")
    run([(best[0], best[1], a, b) for a in RULES for b in RULES],
        f"Stage 2: goal rules (non-goals {best[0]}/{best[1]})")

    by_type = best_rules_by_type(count_by_type(attempts, shifts_by_game), goal_counts(attempts, shifts_by_game), nst_by_player)
    print("\nStage 3: one rule per attempt type (goals end), chosen separately for Corsi for (shooting team's skaters) "
          "and Corsi against (the other team's); best five each")
    for stat, label in (("cf", "Corsi for"), ("ca", "Corsi against")):
        print(f"  {label}: shots on goal / misses / blocks      exact  within 2  within 5  mean |gap|")
        for (n, exact, near, within5, mean), combo in by_type[stat][:5]:
            mark = "  <- what we use now" if combo == (("start",) * 3 if stat == "cf" else ("end",) * 3) else ""
            print(f"    {combo[0]:8s} {combo[1]:8s} {combo[2]:8s}        {exact:5d} {near:9d} {within5:9d} {mean:11.2f}{mark}")

if __name__ == "__main__":
    main()