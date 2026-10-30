"""Test rules for cleaning shifts against the NHL's own season totals.

Run from the repo root with the `nhl` conda environment active, after
ingest_reference.py and stage_season.py:

    python scripts/test_shift_rule.py --season 2023

Read-only. For every skater it totals time on ice and counts shifts under six
rules and compares them with the NHL's timeOnIce and shifts:

    exact duplicates only   what build_onice.py does today
    by shift number         go through a player's shifts in each period in shift-number
                            order, drop any shift that overlaps one already kept
    by shift id             the same, in the order the NHL created the rows
    chain, early            the NHL numbers a player's shifts 1, 2, 3... through the whole
                            game, so keep the longest chain of rows whose shift numbers
                            strictly increase in time order (on ties, prefer earlier rows),
                            then drop overlaps as in "by shift number"
    chain, late             the same, preferring later rows on ties
    spanning out, longest   in each period, drop a shift that overlaps two or more shifts that do
                            not overlap each other (it cannot be real), then among shifts that
                            still overlap keep the longer one

Two shifts overlap when each starts before the other ends. Shifts that only touch
(one ends when the next starts) do not overlap. Identical rows overlap.
"""

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data" / "raw"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
BIG = 10**9


def overlaps(start, end, kept_start, kept_end):
    if start == kept_start and end == kept_end:
        return True
    return start < kept_end and kept_start < end


def drop_overlaps(rows):
    """rows: (start, end) in priority order. Keep each that overlaps none already kept."""
    kept = []
    for start, end in rows:
        if not any(overlaps(start, end, ks, ke) for ks, ke in kept):
            kept.append((start, end))
    return kept


# A row is (period, number, shift_id, start, end).


def rule_exact_duplicates(rows):
    return sorted({(r[3], r[4]) for r in rows})


def per_period_by(rows, position):
    by_period = defaultdict(list)
    for row in rows:
        by_period[row[0]].append(row)
    kept = []
    for period_rows in by_period.values():
        other = 2 if position == 1 else 1  # tie-break: id when sorting by number, number when by id
        period_rows.sort(key=lambda r: (r[position], r[other]))
        kept.extend(drop_overlaps([(r[3], r[4]) for r in period_rows]))
    return kept


def rule_by_number(rows):
    return per_period_by(rows, 1)


def rule_by_id(rows):
    return per_period_by(rows, 2)


def longest_chain(rows, prefer_late):
    """Longest subsequence (in time order) whose shift numbers strictly increase."""
    ordered = sorted(rows, key=lambda r: (r[0], r[3], r[4], r[1]))
    n = len(ordered)
    length, previous = [1] * n, [-1] * n
    for i in range(n):
        best = 0
        for j in range(i):
            if ordered[j][1] < ordered[i][1] and length[j] >= best and length[j] > 0:
                if length[j] > best or prefer_late:
                    best, previous[i] = length[j], j
        length[i] = best + 1
    top = max(length)
    ends = [i for i in range(n) if length[i] == top]
    index = ends[-1] if prefer_late else ends[0]
    chain = []
    while index != -1:
        chain.append(ordered[index])
        index = previous[index]
    return chain[::-1]


def chain_rule(prefer_late):
    def rule(rows):
        chain = longest_chain([r for r in rows if r[1] is not None], prefer_late)
        return per_period_by(chain, 1)

    return rule


def rule_spanning_out_longest(rows):
    kept = []
    by_period = defaultdict(list)
    for row in rows:
        by_period[row[0]].append(row)
    for period_rows in by_period.values():
        period_rows.sort(key=lambda r: (r[1], r[2]))
        unique = list(dict.fromkeys((r[3], r[4]) for r in period_rows))
        survivors = []
        for i, (start, end) in enumerate(unique):
            touching = [
                other for j, other in enumerate(unique)
                if j != i and overlaps(start, end, other[0], other[1])
            ]
            spans = any(
                not overlaps(a[0], a[1], b[0], b[1])
                for x, a in enumerate(touching)
                for b in touching[x + 1:]
            )
            if not spans:
                survivors.append((start, end))
        kept.extend(drop_overlaps(sorted(survivors, key=lambda r: r[0] - r[1])))
    return kept


def totals_per_player(games, rule):
    """{player_id: [seconds, shifts]} for skaters, applying `rule` to each (game, player)."""
    totals = defaultdict(lambda: [0, 0])
    for (_, player_id), rows in games.items():
        kept = rule(rows)
        totals[player_id][0] += sum(end - start for start, end in kept)
        totals[player_id][1] += len(kept)
    return totals


def compare(totals, reference):
    buckets = {"exact": 0, "within 2 s": 0, "3-60 s": 0, "over 60 s": 0}
    higher = lower = same_shifts = 0
    worst = []
    for player_id, ref in reference.items():
        seconds, shifts = totals.get(player_id, (0, 0))
        diff = seconds - ref["toi"]
        if diff == 0:
            buckets["exact"] += 1
        elif abs(diff) <= 2:
            buckets["within 2 s"] += 1
        elif abs(diff) <= 60:
            buckets["3-60 s"] += 1
        else:
            buckets["over 60 s"] += 1
        higher += diff > 2
        lower += diff < -2
        same_shifts += shifts == ref["shifts"]
        worst.append((abs(diff), player_id, ref["name"], diff, shifts - ref["shifts"]))
    worst.sort(reverse=True)
    return buckets, higher, lower, same_shifts, worst[:8]


def main():
    parser = argparse.ArgumentParser(description="Test shift cleaning rules.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    staging = STAGING_ROOT / f"season={args.season}"
    reference_path = RAW_ROOT / f"season={args.season}" / "reference" / "skater_timeonice.json.gz"
    with gzip.open(reference_path, "rb") as handle:
        reference = {
            r["playerId"]: {"toi": r["timeOnIce"], "shifts": r["shifts"], "name": r["skaterFullName"]}
            for r in json.loads(handle.read())["data"]
        }

    con = duckdb.connect()
    goalies = {
        (game_id, player_id)
        for game_id, player_id in con.execute(
            f"select game_id, player_id from '{(staging / 'boxscore_players.parquet').as_posix()}' "
            "where player_group = 'goalies'"
        ).fetchall()
    }
    rows = con.execute(
        f"""
        select game_id, player_id, period, shift_number, shift_id,
               start_game_seconds, end_game_seconds
        from '{(staging / 'shifts.parquet').as_posix()}'
        where start_game_seconds is not null and end_game_seconds is not null
        """
    ).fetchall()

    games = defaultdict(list)  # (game, player) -> [(period, number, shift_id, start, end)]
    for game_id, player_id, period, number, shift_id, start, end in rows:
        if (game_id, player_id) in goalies:
            continue
        games[(game_id, player_id)].append(
            (period, number, BIG if shift_id is None else shift_id, start, end)
        )
    # rows without a shift number sort last in the number-based rules
    for key, items in games.items():
        games[key] = [(p, BIG if n is None else n, i, s, e) for p, n, i, s, e in items]

    rules = {
        "exact duplicates only": lambda items: sorted({(r[3], r[4]) for r in items}),
        "by shift number": rule_by_number,
        "by shift id": rule_by_id,
        "chain, early": chain_rule(False),
        "chain, late": chain_rule(True),
        "spanning out, longest": rule_spanning_out_longest,
    }
    print(f"Season {args.season}: {len(reference)} skaters in the NHL's totals\n")
    print(f"{'rule':24s} {'exact':>6} {'within 2 s':>11} {'3-60 s':>7} {'over 60 s':>10} "
          f"{'we higher':>10} {'we lower':>9} {'same shifts':>12}")
    results = {}
    for name, rule in rules.items():
        buckets, higher, lower, same_shifts, worst = compare(totals_per_player(games, rule), reference)
        results[name] = worst
        print(
            f"{name:24s} {buckets['exact']:>6} {buckets['within 2 s']:>11} {buckets['3-60 s']:>7} "
            f"{buckets['over 60 s']:>10} {higher:>10} {lower:>9} {same_shifts:>12}"
        )

    print("\nLargest remaining differences under 'spanning out, longest'")
    print("player_id  name                     ours minus NHL (s)  ours minus NHL (shifts)")
    for _, player_id, name, diff, shift_diff in results["spanning out, longest"]:
        print(f"{player_id:<10} {name:24s} {diff:>18} {shift_diff:>24}")


if __name__ == "__main__":
    main()