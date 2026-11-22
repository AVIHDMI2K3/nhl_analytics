"""Tests for the helpers of scripts/diagnose_boundary_rules.py."""

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import diagnose_boundary_rules as d  # noqa: E402


def shift(player, team, start, end):
    return {"player_id": player, "team_id": team, "start": start, "end": end}


def test_the_four_rules_include_or_exclude_the_first_and_last_second():
    times = [9, 10, 15, 20, 21]
    by_rule = d.on_ice_by_rule([shift(1, 10, 10, 20)], times)
    seconds = {rule: sorted(s for s, teams in members.items() if 1 in teams[10]) for rule, members in by_rule.items()}
    assert seconds["start"] == [10, 15] and seconds["end"] == [15, 20]
    assert seconds["both"] == [10, 15, 20] and seconds["neither"] == [15]


def attempt(kind, second, team=10, other=20, game=1):
    return {"game_id": game, "game_seconds": second, "attempt_type": kind, "team_id": team, "opponent_team_id": other}


def test_corsi_is_counted_for_the_shooters_skaters_and_against_the_others_under_each_scheme():
    shifts = {1: [shift(1, 10, 0, 100), shift(2, 20, 0, 50), shift(3, 20, 50, 100)]}
    attempts = [attempt("shot-on-goal", 50), attempt("goal", 50), attempt("faceoff", 50)]
    schemes = [d.CURRENT, ("both", "both", "both", "both"), ("start", "end", "end", "start")]
    counts = d.count_corsi(attempts, shifts, schemes)
    current = counts[d.CURRENT]  # shots start-inclusive, goals end-inclusive
    assert current[(1, "cf")] == 2 and current[(3, "ca")] == 1 and current[(2, "ca")] == 1
    both = counts[("both", "both", "both", "both")]
    assert both[(2, "ca")] == 2 and both[(3, "ca")] == 2
    split = counts[("start", "end", "end", "start")]  # shot: other side end-inclusive; goal: other side start-inclusive
    assert split[(2, "ca")] == 1 and split[(3, "ca")] == 1 and split[(1, "cf")] == 2


def test_score_compares_with_nst():
    counter = Counter({(1, "cf"): 10, (1, "ca"): 8, (2, "cf"): 5, (2, "ca"): 5})
    n, cf_exact, ca_exact, near, mean = d.score(counter, {1: (10, 9), 2: (9, 5)})
    assert (n, cf_exact, ca_exact, near) == (2, 1, 1, 1) and mean == (0 + 1 + 4 + 0) / 4


def test_rules_per_attempt_type_are_chosen_separately_for_each_stat():
    shifts = {1: [shift(1, 10, 0, 100), shift(2, 20, 0, 50), shift(3, 20, 50, 100)]}
    attempts = [attempt("shot-on-goal", 50), attempt("blocked-shot", 50), attempt("goal", 50)]
    by_type = d.count_by_type(attempts, shifts)
    assert by_type[("sog", "ca", "end")][2] == 1 and by_type[("sog", "ca", "start")][3] == 1
    goals = d.goal_counts(attempts, shifts)
    assert goals["cf"][1] == 1 and goals["ca"][2] == 1 and goals["ca"][3] == 0
    # NST agrees with: defenders 2 credited with the shot and block (end rule) and the goal
    nst = {1: (3, 0), 2: (0, 3), 3: (0, 0)}
    best = d.best_rules_by_type(by_type, goals, nst)
    sog_rule, _miss_rule, block_rule = best["ca"][0][1]  # no missed shots in the game, so that rule is a tie
    assert best["ca"][0][0][1] == 3 and (sog_rule, block_rule) == ("end", "end")
    assert best["cf"][0][0][4] == 0
