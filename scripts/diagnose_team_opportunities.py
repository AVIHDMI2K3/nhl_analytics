"""First look at power-play opportunities: count them from the penalty events and compare with the NHL.

Run from the repo root with the `nhl` conda environment active, after ingest_reference.py:

    python scripts/diagnose_team_opportunities.py --season 2025

Team power-play % is goals / opportunities and penalty-kill % is 1 - goals against / times shorthanded, so
the opportunities have to be counted first. The NHL's team reports give them (ppOpportunities,
timesShorthanded) and the goals (powerPlayGoalsFor, ppGoalsAgainst). This script:

  1. prints the columns of events.parquet that look like penalty details, the penalty minutes we have and
     how often each occurs, so we can see what a penalty row tells us;
  2. counts opportunities two simple ways and compares each with the NHL, per team:
       all      every penalty of 2, 4 or 5 minutes gives the other team one opportunity
       offset   the same, but penalties of the same length to both teams at the same second cancel
  3. tries two variants of the offset count (majors not offset; double minors counted twice) and prints
     the pairs of penalties the offset rule cancels, by penalty type, so we can see which kind of pair
     the NHL does not cancel;
  4. prints the teams that differ most under the best count.

Nothing is written. It is a start: where the counts differ shows which rule is missing (majors, double
minors, penalties during a power play, penalty shots, coincident penalties of different lengths).
"""

import argparse
import gzip
import heapq
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data" / "raw"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
COUNTED_MINUTES = (2, 4, 5)


def at_regulation_end(row):
    return row["game_seconds"] == 3600 and row.get("period_type") == "REG"


def kept(penalties, ignore_end=None, late_seconds=0):
    """Penalty rows without those at the very end of regulation (3600 s): all of them with
    ignore_end="regulation", only in games that did not go to overtime with "no_overtime"
    (rows then carry game_has_ot). With `late_seconds`, also the penalties in the last that many seconds
    of regulation in games that did not go to overtime."""
    def late(row):
        return (late_seconds and row.get("period_type") == "REG" and not row.get("game_has_ot")
                and row["game_seconds"] >= 3600 - late_seconds)

    if ignore_end is None:
        return [r for r in penalties if not late(r)]
    if ignore_end == "regulation":
        return [r for r in penalties if not at_regulation_end(r) and not late(r)]
    return [r for r in penalties if not (at_regulation_end(r) and not r.get("game_has_ot")) and not late(r)]


def count_opportunities_clock(penalties, ignore_end=None, steps=False):
    """Opportunities counted with a penalty clock, per game and team: ({team: opportunities}, {team:
    times shorthanded}).

    Every 2- or 5-minute penalty is a unit that runs 2 (or 5) minutes. A team serves two units at once
    (5-on-3); a third waits for a free place, and the second half of a double minor starts when the first
    ends. A team's net disadvantage is its unexpired units (waiting ones included) minus the other team's.
    When it goes up at a penalty (all penalties at one second taken together), the other team gets that
    many opportunities, so penalties of both teams at one second cancel, and so does a penalty taken
    while the other team is already shorthanded by as much or more. With `steps`, a rise caused by the
    other team's penalty running out counts too (the penalty outlasted it).
    """
    opportunities, shorthanded = Counter(), Counter()
    games = defaultdict(list)
    for row in kept(penalties, ignore_end):
        if row["penalty_minutes"] in COUNTED_MINUTES:
            games[row["game_id"]].append(row)
    for rows in games.values():
        teams = sorted({r["event_owner_team_id"] for r in rows} | {r["opponent_team_id"] for r in rows})
        ends = {team: [] for team in teams}
        free = {team: [0, 0] for team in teams}
        previous = {(x, y): 0 for x in teams for y in teams if x != y}
        by_second = defaultdict(list)
        for row in rows:
            by_second[row["game_seconds"]].append(row)
        times = list(by_second)
        heapq.heapify(times)
        seen = set()

        def active(team, now):
            return sum(1 for end in ends[team] if end > now)

        def count(now, may_count):
            for (x, y), before in previous.items():
                net = max(active(x, now) - active(y, now), 0)
                if may_count and net > before:
                    opportunities[y] += net - before
                    shorthanded[x] += net - before
                previous[(x, y)] = net

        while times:
            now = heapq.heappop(times)
            if now in seen:
                continue
            seen.add(now)
            count(now, steps)  # the state after anything that ran out; counts only with `steps`
            for row in by_second.get(now, []):
                team, minutes = row["event_owner_team_id"], row["penalty_minutes"]
                not_before = now
                for _ in range(2 if minutes == 4 else 1):
                    place = min(range(2), key=lambda i: free[team][i])
                    start = max(not_before, free[team][place])
                    free[team][place] = not_before = start + (300 if minutes == 5 else 120)
                    ends[team].append(not_before)
                    heapq.heappush(times, not_before)
            count(now, True)
    return opportunities, shorthanded


def count_opportunities(penalties, offset=False, offset_majors=True, double_minor_twice=False,
                        split_double_minors=False, ignore_end=None, late_seconds=0, minor_vs_major=False):
    """({team_id: opportunities}, {team_id: times shorthanded}) from penalty event rows.

    `penalties` have game_id, game_seconds, event_owner_team_id (the penalized team), penalty_minutes and
    `opponent_team_id`. Only penalties of COUNTED_MINUTES are used. With `offset`, penalties of the same
    length given to both teams at the same second cancel one for one (not the 5-minute ones when
    `offset_majors` is False). With `double_minor_twice`, a 4-minute penalty counts as two. With
    `split_double_minors`, a 4-minute penalty is two 2-minute penalties before anything is offset, so a
    2-minute penalty to the other team at the same second cancels one of them. With `minor_vs_major`, a
    minor does not count when the other team gets a major at the same second (the major still counts).
    With `late_seconds`, penalties in the last seconds of regulation (no overtime) are left out.
    """
    taken = Counter()  # (game, second, minutes, penalized team) -> penalties
    opponent = {}
    for row in kept(penalties, ignore_end, late_seconds):
        if row["penalty_minutes"] not in COUNTED_MINUTES:
            continue
        minutes, parts = row["penalty_minutes"], 1
        if split_double_minors and minutes == 4:
            minutes, parts = 2, 2
        key = (row["game_id"], row["game_seconds"], minutes, row["event_owner_team_id"])
        taken[key] += parts
        opponent[key] = row["opponent_team_id"]
    opportunities, shorthanded = Counter(), Counter()
    for key, number in taken.items():
        game, second, minutes, team = key
        if offset and (offset_majors or minutes != 5):
            other = taken.get((game, second, minutes, opponent[key]), 0)
            number = max(number - other, 0)
        if minor_vs_major and minutes == 2:
            number = max(number - taken.get((game, second, 5, opponent[key]), 0), 0)
        if double_minor_twice and minutes == 4:
            number *= 2
        shorthanded[team] += number
        opportunities[opponent[key]] += number
    return opportunities, shorthanded


def cancelled_pairs(penalties):
    """Counter of (minutes, type of one penalty, type of the other) for each pair the offset rule cancels,
    types sorted so a pair is counted once. Pairs are matched in order within a game and second."""
    groups = defaultdict(list)
    for row in penalties:
        if row["penalty_minutes"] in COUNTED_MINUTES:
            groups[(row["game_id"], row["game_seconds"], row["penalty_minutes"])].append(row)
    pairs = Counter()
    for (_, _, minutes), rows in groups.items():
        teams = sorted({r["event_owner_team_id"] for r in rows})
        if len(teams) != 2:
            continue
        first = [r for r in rows if r["event_owner_team_id"] == teams[0]]
        second = [r for r in rows if r["event_owner_team_id"] == teams[1]]
        for a, b in zip(first, second):
            pairs[(minutes, *sorted((str(a.get("penalty_type_code")), str(b.get("penalty_type_code")))))] += 1
    return pairs


def load_report(season, name):
    with gzip.open(RAW_ROOT / f"season={season}" / "reference" / f"{name}.json.gz", "rb") as handle:
        return {r["teamId"]: r for r in json.loads(handle.read())["data"]}


def compare(ours, nhl_values):
    """(exact, teams, our total, NHL total) for {team: value} dicts."""
    exact = sum(1 for t, v in nhl_values.items() if ours.get(t, 0) == v)
    return exact, len(nhl_values), sum(ours.get(t, 0) for t in nhl_values), sum(nhl_values.values())


def main():
    parser = argparse.ArgumentParser(description="Count power-play opportunities from penalty events.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    path = STAGING_ROOT / f"season={args.season}" / "events.parquet"
    columns = pq.ParquetFile(path).schema_arrow.names
    detail = [c for c in columns if any(word in c for word in ("penalt", "desc", "type", "duration", "minor", "major"))]
    print(f"Season {args.season}: event columns that may describe a penalty: {detail}")
    wanted = list(dict.fromkeys(["game_id", "event_type", "period_type", "game_seconds", "event_owner_team_id",
                                 "penalty_minutes"] + detail))
    events = pq.read_table(path, columns=[c for c in wanted if c in columns]).to_pylist()
    games = {g["game_id"]: g for g in pq.read_table(
        STAGING_ROOT / f"season={args.season}" / "games.parquet",
        columns=["game_id", "home_team_id", "away_team_id"]).to_pylist()}

    penalties = []
    for event in events:
        if event["event_type"] != "penalty":
            continue
        game = games[event["game_id"]]
        home, away = game["home_team_id"], game["away_team_id"]
        event["opponent_team_id"] = away if event["event_owner_team_id"] == home else home
        penalties.append(event)
    print(f"Penalty events: {len(penalties)}; penalty minutes and how often: "
          f"{sorted(Counter(p['penalty_minutes'] for p in penalties).items(), key=lambda kv: (kv[0] is None, kv[0]))}")
    for column in detail:
        if column in ("penalty_minutes",):
            continue
        values = Counter(p.get(column) for p in penalties)
        if len(values) <= 25:
            print(f"  {column}: {dict(values.most_common())}")

    report = load_report(args.season, "team_powerplay")
    against = load_report(args.season, "team_penaltykill")
    nhl_opp = {t: r["ppOpportunities"] for t, r in report.items()}
    nhl_short = {t: r["timesShorthanded"] for t, r in against.items()}
    best = None
    variants = (
        ("all", {}),
        ("offset", {"offset": True}),
        ("offset, majors not offset", {"offset": True, "offset_majors": False}),
        ("offset, double minors twice", {"offset": True, "double_minor_twice": True}),
    )
    for label, options in variants:
        opp, short = count_opportunities(penalties, **options)
        a, b = compare(opp, nhl_opp), compare(short, nhl_short)
        print(f"\n{label}: opportunities exact for {a[0]} of {a[1]} teams (ours {a[2]}, NHL {a[3]}); "
              f"times shorthanded exact for {b[0]} of {b[1]} teams (ours {b[2]}, NHL {b[3]})")
        if best is None or a[0] + b[0] > best[0]:
            best = (a[0] + b[0], label, opp, short)
    _, label, opp, short = best
    print(f"\nPairs the offset rule cancels (minutes, types), season {args.season}:")
    for pair, number in cancelled_pairs(penalties).most_common(12):
        print(f"  {number:4d}  {pair}")
    names = {t: r.get("teamFullName", t) for t, r in report.items()}
    print(f"\nTeams furthest from the NHL under '{label}' (ours minus NHL):")
    rows = sorted(nhl_opp, key=lambda t: -abs(opp.get(t, 0) - nhl_opp[t]))[:8]
    for t in rows:
        print(f"  {names[t]:26s} opportunities {opp.get(t, 0):4d} vs {nhl_opp[t]:4d}  "
              f"shorthanded {short.get(t, 0):4d} vs {nhl_short.get(t, 0):4d}")


if __name__ == "__main__":
    main()