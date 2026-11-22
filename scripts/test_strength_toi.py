"""Test ways of splitting time on ice by strength against the NHL's own totals.

Run from the repo root with the `nhl` conda environment active, after build_onice.py
and ingest_reference.py:

    python scripts/test_strength_toi.py --season 2023

Read-only. Builds stints from data/intermediate/season=YYYY/shifts_clean.parquet and, for
each method, adds up every skater's seconds at even strength (ev), power play (pp) and
shorthanded (sh), then compares with the NHL's evTimeOnIce, ppTimeOnIce and shTimeOnIce.

Methods:
    shifts, goalie adj   skaters on the ice, a team without a goalie on the ice has one fewer
    blips <= N s         the same, but a stint of at most N seconds whose strength differs from
                         the stints on both sides (which agree) takes their strength. Shift
                         data is accurate to about a second, so line changes can leave a team
                         briefly with one skater too many or too few.

(The raw skater count and the situationCode methods were tried on 2023 and 2025 and are far
worse, so they are no longer run.)

Each method is shown for all skaters, and for the skaters whose total time on ice is within
2 s of the NHL's, so that only the split by strength is being tested.
"""

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

import stints as st  # noqa: E402

RAW_ROOT = REPO_ROOT / "data" / "raw"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"
STRENGTHS = ("ev", "pp", "sh")
REFERENCE_FIELDS = {"ev": "evTimeOnIce", "pp": "ppTimeOnIce", "sh": "shTimeOnIce"}


def read_columns(path, columns):
    return pq.read_table(path, columns=columns).to_pydict()


def group_rows(columns, key="game_id"):
    names = list(columns)
    groups = defaultdict(list)
    for i in range(len(columns[key])):
        groups[columns[key][i]].append({name: columns[name][i] for name in names})
    return groups


BLIP_SECONDS = (2, 5, 10)


def methods(game_stints):
    def base(stint, side):
        return st.strength_from_shifts(stint, side, adjust_goalie=True)

    result = {"shifts, goalie adj": base}
    for seconds in BLIP_SECONDS:
        result[f"blips <= {seconds} s"] = st.smoothed_label_for(game_stints, base, seconds)
    return result


def bucket(diff):
    diff = abs(diff)
    if diff == 0:
        return "exact"
    if diff <= 2:
        return "<=2 s"
    if diff <= 10:
        return "<=10 s"
    if diff <= 60:
        return "<=60 s"
    return ">60 s"


def main():
    parser = argparse.ArgumentParser(description="Test strength time-on-ice methods.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    staging = STAGING_ROOT / f"season={args.season}"
    games_columns = read_columns(staging / "games.parquet", ["game_id", "home_team_id", "away_team_id"])
    games = {
        g: {"game_id": g, "home_team_id": h, "away_team_id": a}
        for g, h, a in zip(games_columns["game_id"], games_columns["home_team_id"], games_columns["away_team_id"])
    }
    shifts = group_rows(
        read_columns(
            INTERMEDIATE_ROOT / f"season={args.season}" / "shifts_clean.parquet",
            ["game_id", "player_id", "team_id", "period", "start_game_seconds", "end_game_seconds", "is_goalie"],
        )
    )
    reference_path = RAW_ROOT / f"season={args.season}" / "reference" / "skater_timeonice.json.gz"
    with gzip.open(reference_path, "rb") as handle:
        reference = {r["playerId"]: r for r in json.loads(handle.read())["data"]}

    totals = defaultdict(lambda: defaultdict(int))  # method -> (player, strength) -> seconds
    special = defaultdict(int)
    for game_id, game_shifts in shifts.items():
        game_stints = st.build_stints(games[game_id], game_shifts)
        for name, label_for in methods(game_stints).items():
            for key, seconds in st.seconds_by_strength(game_stints, label_for).items():
                totals[name][key] += seconds
        for stint in game_stints:  # how much special-teams time comes from very short stints
            length = stint["end"] - stint["start"]
            for side in st.SIDES:
                if st.strength_from_shifts(stint, side) != "ev":
                    player_seconds = length * len(stint[f"{side}_skater_ids"])
                    special["all"] += player_seconds
                    for limit in BLIP_SECONDS:
                        if length <= limit:
                            special[limit] += player_seconds

    print(f"Season {args.season}: {len(reference)} skaters in the NHL's totals")
    print(
        "NHL totals (seconds): "
        + ", ".join(f"{s} {sum(r[REFERENCE_FIELDS[s]] for r in reference.values())}" for s in STRENGTHS)
    )
    print("\nPlayer-seconds at pp or sh (shift counts, goalie adjusted) that come from stints of at most:")
    for limit in BLIP_SECONDS:
        print(f"  {limit:>2d} s: {special[limit]} of {special['all']}")

    matching = {
        p
        for p, ref in reference.items()
        if abs(sum(totals["shifts, goalie adj"].get((p, s), 0) for s in STRENGTHS) - ref["timeOnIce"]) <= 2
    }
    order = ["exact", "<=2 s", "<=10 s", "<=60 s", ">60 s"]
    for title, subset in (("all skaters", set(reference)), ("skaters whose total time on ice is within 2 s", matching)):
        print(f"\n##### {title}: {len(subset)}")
        for name, per_player in totals.items():
            print(f"\n=== {name} ===")
            print(f"{'strength':9s}" + "".join(f"{b:>9s}" for b in order) + f"{'our total':>12s}{'NHL total':>12s}")
            for strength in STRENGTHS:
                counts = dict.fromkeys(order, 0)
                ours_total = nhl_total = 0
                for player_id in subset:
                    ref = reference[player_id][REFERENCE_FIELDS[strength]]
                    ours = per_player.get((player_id, strength), 0)
                    ours_total += ours
                    nhl_total += ref
                    counts[bucket(ours - ref)] += 1
                print(
                    f"{strength:9s}" + "".join(f"{counts[b]:>9d}" for b in order) + f"{ours_total:>12d}{nhl_total:>12d}"
                )


if __name__ == "__main__":
    main()
