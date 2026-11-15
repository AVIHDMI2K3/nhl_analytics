"""Where does our 5v5 time on ice differ from Natural Stat Trick's? (Phase 5)

Our 5v5 team time is about 0.06% above NST's while the all-situations time matches. This splits our even-strength
time into states (5v5 with both goalies in, 4v4, 3v3, and every state with a goalie out) and compares it with NST's
team tables for 5v5, EV (all even strength) and 3v3. NST has no 4v4 option, so its 4v4 plus anything else is
what is left of EV after 5v5 and 3v3. Files (counts, regular season, venue All) in one folder:

    nst_teams_5v5_<season>.csv, nst_teams_ev_<season>.csv, nst_teams_3v3_<season>.csv

Run from the repo root with the `nhl` environment active:

    python scripts/diagnose_nst_time_by_strength.py --season 2025 --folder data/reference/nst
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_against_nst import TEAM_NAMES, normalize_name, number, read_nst  # noqa: E402

PARTS = ("5v5", "4v4", "3v3", "goalie out", "other")


def part_of(row):
    """Which of PARTS an even-strength state row belongs to."""
    skaters = (row["skaters_for"], row["skaters_against"])
    if (row["goalies_for"], row["goalies_against"]) != (1, 1):
        return "goalie out"
    return {(5, 5): "5v5", (4, 4): "4v4", (3, 3): "3v3"}.get(skaters, "other")


def minutes_by_team(rows):
    """{team_id: {part: minutes}} for the even-strength state rows of team_game_strength."""
    totals = defaultdict(lambda: defaultdict(float))
    for row in rows:
        if row["strength"] == "ev":
            totals[row["team_id"]][part_of(row)] += row["seconds"] / 60
    return totals


def nst_minutes(path):
    """{team abbreviation: TOI minutes} of one NST team export."""
    result = {}
    for row in read_nst(path):
        abbrev = TEAM_NAMES.get(normalize_name(row["Team"]))
        if abbrev:
            result[abbrev] = number(row["TOI"])
    return result


def compare(ours, five, ev, three):
    """Per team: our minutes by part, NST's 5v5, 3v3 and EV, and what NST leaves for 4v4 and the rest."""
    table = {}
    for team, parts in ours.items():
        if team not in five or team not in ev or team not in three:
            continue
        mine = {part: parts.get(part, 0.0) for part in PARTS}
        table[team] = {
            "ours": mine, "ours_ev": sum(mine.values()), "ours_4v4_rest": mine["4v4"] + mine["goalie out"] + mine["other"],
            "nst_5v5": five[team], "nst_3v3": three[team], "nst_ev": ev[team],
            "nst_4v4_rest": ev[team] - five[team] - three[team],
        }
    return table


def main():
    parser = argparse.ArgumentParser(description="Compare our even-strength time by state with NST.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--folder", type=Path, required=True)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    from build_season_display import team_abbrevs

    metrics = REPO_ROOT / "data" / "metrics" / f"season={args.season}"
    abbrevs = team_abbrevs(REPO_ROOT / "data" / "staging" / f"season={args.season}")
    ours = {abbrevs[team_id]: parts for team_id, parts in minutes_by_team(
        pq.read_table(metrics / "team_game_strength.parquet").to_pylist()).items()}
    names = [f"nst_teams_{situation}_{args.season}.csv" for situation in ("5v5", "ev", "3v3")]
    missing = [name for name in names if not (args.folder / name).exists()]
    if missing:
        sys.exit(f"Missing in {args.folder}: {', '.join(missing)}")
    five, ev, three = (nst_minutes(args.folder / name) for name in names)
    table = compare(ours, five, ev, three)

    def total(getter):
        return sum(getter(row) for row in table.values())

    print(f"Season {args.season}: even-strength time in minutes, {len(table)} teams, league totals")
    print(f"  5v5          ours {total(lambda r: r['ours']['5v5']):10.1f}   NST {total(lambda r: r['nst_5v5']):10.1f}")
    print(f"  3v3          ours {total(lambda r: r['ours']['3v3']):10.1f}   NST {total(lambda r: r['nst_3v3']):10.1f}")
    print(f"  4v4 + rest   ours {total(lambda r: r['ours_4v4_rest']):10.1f}   NST {total(lambda r: r['nst_4v4_rest']):10.1f}  (EV - 5v5 - 3v3)")
    print(f"  EV total     ours {total(lambda r: r['ours_ev']):10.1f}   NST {total(lambda r: r['nst_ev']):10.1f}")
    print("  ours, split: " + ", ".join(f"{part} {total(lambda r, p=part: r['ours'][p]):.1f}" for part in PARTS))
    print("\nPer team, difference ours - NST in minutes (5v5, 3v3, 4v4 + rest, EV), largest 5v5 gaps first:")
    for team, row in sorted(table.items(), key=lambda item: -abs(item[1]["ours"]["5v5"] - item[1]["nst_5v5"]))[:10]:
        print(f"  {team}  {row['ours']['5v5'] - row['nst_5v5']:+7.1f} {row['ours']['3v3'] - row['nst_3v3']:+7.1f} "
              f"{row['ours_4v4_rest'] - row['nst_4v4_rest']:+7.1f} {row['ours_ev'] - row['nst_ev']:+7.1f}")


if __name__ == "__main__":
    main()