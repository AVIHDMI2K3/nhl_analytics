"""Compare our advanced on-ice tables with Natural Stat Trick (NST) season exports (Phase 5).

Download four CSVs from naturalstattrick.com for one regular season (counts, no score adjustment, venue All):
player season totals, on-ice, 5v5 and all situations; team season totals, 5v5 and all situations. Name them
nst_skaters_5v5_2023.csv, nst_skaters_all_2023.csv, nst_teams_5v5_2023.csv, nst_teams_all_2023.csv (the number is
the season's start year, which is also our season number) and put them in one folder. Run from the repo root with
the `nhl` conda environment active, after build_player_advanced.py and build_team_advanced.py:

    python scripts/check_against_nst.py --season 2023 --folder data/reference/nst

Compares, for each file, time on ice (minutes, to 0.1), Corsi, Fenwick, shots on goal and goals for and against.
Skaters are matched by name and team(s); a traded player is one NST row, so it is matched with our combined row.
Prints, per statistic, how many skaters (or teams) agree exactly, the totals, and the largest differences, then
lists skaters that could not be matched. Expected-goals, danger and zone-start columns are not compared.
"""

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

METRICS_ROOT = REPO_ROOT / "data" / "metrics"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
STATS = ("CF", "CA", "FF", "FA", "SF", "SA", "GF", "GA")
OUR_COLUMNS = {"CF": "cf", "CA": "ca", "FF": "ff", "FA": "fa", "SF": "sf", "SA": "sa", "GF": "gf", "GA": "ga"}
TOI_TOLERANCE_MINUTES = 0.1
NST_ABBREVIATIONS = {"S.J": "SJS", "N.J": "NJD", "T.B": "TBL", "L.A": "LAK"}
TEAM_NAMES = {
    "anaheim ducks": "ANA",
    "arizona coyotes": "ARI",
    "boston bruins": "BOS",
    "buffalo sabres": "BUF",
    "calgary flames": "CGY",
    "carolina hurricanes": "CAR",
    "chicago blackhawks": "CHI",
    "colorado avalanche": "COL",
    "columbus blue jackets": "CBJ",
    "dallas stars": "DAL",
    "detroit red wings": "DET",
    "edmonton oilers": "EDM",
    "florida panthers": "FLA",
    "los angeles kings": "LAK",
    "minnesota wild": "MIN",
    "montreal canadiens": "MTL",
    "nashville predators": "NSH",
    "new jersey devils": "NJD",
    "new york islanders": "NYI",
    "new york rangers": "NYR",
    "ottawa senators": "OTT",
    "philadelphia flyers": "PHI",
    "pittsburgh penguins": "PIT",
    "san jose sharks": "SJS",
    "seattle kraken": "SEA",
    "st louis blues": "STL",
    "tampa bay lightning": "TBL",
    "toronto maple leafs": "TOR",
    "utah hockey club": "UTA",
    "utah mammoth": "UTA",
    "vancouver canucks": "VAN",
    "vegas golden knights": "VGK",
    "washington capitals": "WSH",
    "winnipeg jets": "WPG",
}


def normalize_name(name):
    """Lower case, no accents or punctuation: 'Alexis Lafrenière' and 'Alexis Lafreniere' match."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9 ]", "", text.lower().replace("-", " ").replace(".", "")).strip()


def team_set(text):
    """{'CGY', 'ANA'} from NST's 'CGY, ANA' (and its S.J-style abbreviations) or from our 'ANA, CGY'."""
    parts = [part.strip().strip('"') for part in (text or "").split(",")]
    return frozenset(NST_ABBREVIATIONS.get(part, part) for part in parts if part)


def number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def read_nst(path):
    """Rows of an NST export as dicts (the byte order mark and the unnamed first column are dropped)."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [{key: value for key, value in row.items() if key} for row in rows if any(row.values())]


def compare_column(pairs):
    """(compared, exact, ours total, NST total, worst difference) for [(ours, nst, label)] with both present."""
    usable = [(o, n, label) for o, n, label in pairs if o is not None and n is not None]
    worst = max(usable, key=lambda p: abs(p[0] - p[1]), default=(0, 0, None))
    return (
        len(usable),
        sum(1 for o, n, _ in usable if o == n),
        sum(o for o, _, _ in usable),
        sum(n for _, n, _ in usable),
        worst[0] - worst[1],
        worst[2],
    )


def last_name(name):
    """The last word of a normalized name ('Nicholas Paul' and 'Nick Paul' both give 'paul')."""
    words = normalize_name(name).split()
    return words[-1] if words else ""


def match_skaters(nst_rows, our_rows):
    """({nst index: our row}, [unmatched nst indices], [our rows not matched]) by name and team set, then, for the
    rest, by team set, last name and games played (first names differ: Nick and Nicholas). `our_rows` are the
    combined row of a traded player or the single team row, with name, teams and games_played."""
    by_key = {}
    for row in our_rows:
        by_key.setdefault((normalize_name(row["name"]), team_set(row["teams"])), []).append(row)
    matched, leftover, used = {}, [], set()
    for index, row in enumerate(nst_rows):
        candidates = [
            c for c in by_key.get((normalize_name(row["Player"]), team_set(row["Team"])), []) if id(c) not in used
        ]
        if candidates:
            matched[index] = candidates[0]
            used.add(id(candidates[0]))
        else:
            leftover.append(index)
    unmatched = []
    for index in leftover:
        row = nst_rows[index]
        close = [
            c
            for c in our_rows
            if id(c) not in used
            and team_set(c["teams"]) == team_set(row["Team"])
            and c["games_played"] == number(row["GP"])
            and last_name(c["name"]) == last_name(row["Player"])
        ]
        if len(close) == 1:
            matched[index] = close[0]
            used.add(id(close[0]))
        else:
            unmatched.append(index)
    return matched, unmatched, [c for c in our_rows if id(c) not in used]


def within(pairs, tolerance):
    """How many of the pairs with both numbers differ by at most `tolerance`."""
    return sum(1 for o, n, _ in pairs if o is not None and n is not None and abs(o - n) <= tolerance)


def report(pairs_by_stat, show):
    for stat, pairs in pairs_by_stat.items():
        compared, exact, mine, theirs, worst, who = compare_column(pairs)
        print(
            f"  {stat:4s} exact {exact:4d}/{compared:<4d} within 2: {within(pairs, 2):4d}  within 5: {within(pairs, 5):4d}  "
            f"ours {mine:9.1f} NST {theirs:9.1f}  worst {worst:+.1f} ({who})"
        )
    if show:
        for stat in ("CF", "GF"):
            ranked = sorted(
                (p for p in pairs_by_stat[stat] if p[0] is not None and p[1] is not None and p[0] != p[1]),
                key=lambda p: -abs(p[0] - p[1]),
            )[:show]
            if ranked:
                print(
                    f"  largest {stat} differences: "
                    + "; ".join(f"{label} ours {o:g} NST {n:g}" for o, n, label in ranked)
                )


def skater_pairs(nst_rows, matched):
    pairs = {stat: [] for stat in ("TOI",) + STATS}
    for index, ours in matched.items():
        row = nst_rows[index]
        label = f"{row['Player']} {row['Team']}"
        minutes = number(row["TOI"])
        pairs["TOI"].append((None if ours is None else round(ours["seconds"] / 60, 1), minutes, label))
        for stat in STATS:
            pairs[stat].append((ours[OUR_COLUMNS[stat]], number(row[stat]), label))
    return pairs


def toi_report(pairs):
    compared = [(o, n, label) for o, n, label in pairs["TOI"] if o is not None and n is not None]
    within = sum(1 for o, n, _ in compared if abs(o - n) <= TOI_TOLERANCE_MINUTES)
    worst = max(compared, key=lambda p: abs(p[0] - p[1]), default=(0, 0, None))
    print(
        f"  TOI  within {TOI_TOLERANCE_MINUTES} min {within:4d}/{len(compared):<4d} "
        f"ours {sum(o for o, _, _ in compared):9.1f} NST {sum(n for _, n, _ in compared):9.1f}  worst {worst[0] - worst[1]:+.1f} ({worst[2]})"
    )


def main():
    parser = argparse.ArgumentParser(description="Compare our advanced tables with Natural Stat Trick exports.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--show", type=int, default=5, help="how many largest differences to print per file")
    args = parser.parse_args()
    import pyarrow.parquet as pq
    from build_season_display import team_abbrevs

    metrics = METRICS_ROOT / f"season={args.season}"
    abbrevs = team_abbrevs(STAGING_ROOT / f"season={args.season}")
    players = pq.read_table(metrics / "player_season_advanced.parquet").to_pylist()
    teams = pq.read_table(metrics / "team_season_advanced.parquet").to_pylist()

    for situation, label in (("5v5", "5v5"), ("all", "all situations")):
        path = args.folder / f"nst_skaters_{situation}_{args.season}.csv"
        if not path.exists():
            print(f"\nSkaters, {label}: {path.name} not found, skipped")
            continue
        nst_rows = read_nst(path)
        ours = [r for r in players if r["situation"] == situation and (r["kind"] == "total" or r["teams"] == r["team"])]
        matched, unmatched, spare = match_skaters(nst_rows, ours)
        pairs = skater_pairs(nst_rows, matched)
        print(
            f"\nSkaters, {label}: {len(nst_rows)} in NST, {len(matched)} matched, {len(unmatched)} NST rows unmatched, "
            f"{len(spare)} of our rows unmatched"
        )
        toi_report(pairs)
        report({stat: pairs[stat] for stat in STATS}, args.show)
        if unmatched:
            print(
                "  NST rows not matched: "
                + "; ".join(f"{nst_rows[i]['Player']} ({nst_rows[i]['Team']})" for i in unmatched[:15])
            )
        if spare:
            print("  our rows not matched: " + "; ".join(f"{r['name']} ({r['teams']})" for r in spare[:15]))

    for situation, label in (("5v5", "5v5"), ("all", "all situations")):
        path = args.folder / f"nst_teams_{situation}_{args.season}.csv"
        if not path.exists():
            print(f"\nTeams, {label}: {path.name} not found, skipped")
            continue
        nst_rows = read_nst(path)
        ours = {(r.get("team") or abbrevs.get(r["team_id"])): r for r in teams if r["situation"] == situation}
        pairs = {stat: [] for stat in ("TOI",) + STATS}
        missing = []
        for row in nst_rows:
            abbrev = TEAM_NAMES.get(normalize_name(row["Team"]))
            mine = ours.get(abbrev)
            if mine is None:
                missing.append(row["Team"])
                continue
            pairs["TOI"].append((round(mine["seconds"] / 60, 1), number(row["TOI"]), abbrev))
            for stat in STATS:
                pairs[stat].append((mine[OUR_COLUMNS[stat]], number(row[stat]), abbrev))
        print(f"\nTeams, {label}: {len(nst_rows)} in NST" + (f"; no match for {missing}" if missing else ""))
        toi_report(pairs)
        report({stat: pairs[stat] for stat in STATS}, args.show)


if __name__ == "__main__":
    main()
