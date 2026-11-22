"""Check the base-table logic against independent numbers, before anything is built from it.

Run from the repo root with the `nhl` conda environment active, after build_onice.py and
build_shot_attempts.py for the season:

    python scripts/check_base_tables.py --season 2023
    python scripts/check_base_tables.py --season 2024
    python scripts/check_base_tables.py --season 2025

Read-only. It builds the stints and the player and team rows in memory (the same code a
build script would use) and writes nothing. Checks:

  1. Seconds: the player rows add up to the stints' player-seconds, exactly.
  2. Time on ice by strength against the NHL's season totals (skipped when a season has
     games without shift data).
  3. Plus/minus per player per game against the boxscore. Plus/minus is worked out from
     the rows with the NHL rule (see base_tables.plus_minus), so it tests goals for and
     against by strength end to end.
  4. Goals, shots on goal and power-play goals per player per game against the boxscore.
  5. Totals: attempts counted in the team rows equal the attempts that fall inside a stint.
  6. Who was on the ice: the stint's skaters at each attempt against the skaters Phase 3
     stored with the attempt.
  7. How many rows there are, and which states take the most time.
  8. The other counting stats (assists, hits, giveaways, takeaways, blocks, penalty minutes)
     per player per game against the boxscore, faceoff percentage against the boxscore's,
     and whether the NHL's event owner team is the team the player is on, per column.
"""

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

import base_tables  # noqa: E402
from stints import SIDES, StintIndex, build_stints, stint_rows  # noqa: E402

RAW_ROOT = REPO_ROOT / "data" / "raw"
STAGING_ROOT = REPO_ROOT / "data" / "staging"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
STRENGTHS = ("ev", "pp", "sh")
REFERENCE_FIELDS = {"ev": "evTimeOnIce", "pp": "ppTimeOnIce", "sh": "shTimeOnIce"}
SHIFT_COLUMNS = [
    "game_id",
    "player_id",
    "team_id",
    "period",
    "start_game_seconds",
    "end_game_seconds",
    "is_goalie",
]
ATTEMPT_COLUMNS = [
    "game_id",
    "game_seconds",
    "attempt_type",
    "shooter_id",
    "blocker_id",
    "blocker_is_teammate",
    "is_home",
    "has_on_ice",
    "skater_ids_for",
    "skater_ids_against",
]
EVENT_COLUMNS = [
    "game_id",
    "event_type",
    "period_type",
    "game_seconds",
    "event_owner_team_id",
    "assist1_player_id",
    "assist2_player_id",
    "hitting_player_id",
    "hittee_player_id",
    "player_id",
    "winning_player_id",
    "losing_player_id",
    "committed_by_player_id",
    "drawn_by_player_id",
    "penalty_minutes",
]


def group_by_game(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["game_id"]].append(row)
    return groups


def compare(title, ours, official):
    """Print how many per-player-game values match the boxscore exactly."""
    exact = sum(1 for key, value in official.items() if ours.get(key, 0) == value)
    worst = sorted(
        (
            (abs(ours.get(key, 0) - value), key, ours.get(key, 0) - value)
            for key, value in official.items()
            if ours.get(key, 0) != value
        ),
        reverse=True,
    )
    print(
        f"   {title}: {exact} of {len(official)} exact ({100 * exact / len(official):.2f}%); "
        f"ours {sum(ours.get(k, 0) for k in official)}, boxscore {sum(official.values())}"
    )
    for _, (game_id, player_id), difference in worst[:3]:
        print(f"      {game_id} {player_id} ours minus boxscore {difference:+d}")


def main():
    parser = argparse.ArgumentParser(description="Check the base-table logic.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    staging = STAGING_ROOT / f"season={args.season}"

    games_columns = pq.read_table(
        staging / "games.parquet", columns=["game_id", "home_team_id", "away_team_id"]
    ).to_pylist()
    games = {g["game_id"]: g for g in games_columns}
    shifts = group_by_game(
        pq.read_table(
            INTERMEDIATE_ROOT / f"season={args.season}" / "shifts_clean.parquet", columns=SHIFT_COLUMNS
        ).to_pylist()
    )
    attempts = group_by_game(
        pq.read_table(
            METRICS_ROOT / f"season={args.season}" / "shot_attempts.parquet", columns=ATTEMPT_COLUMNS
        ).to_pylist()
    )
    box = pq.read_table(
        staging / "boxscore_players.parquet",
        columns=[
            "game_id",
            "player_id",
            "player_group",
            "plus_minus",
            "goals",
            "sog",
            "power_play_goals",
            "assists",
            "hits",
            "giveaways",
            "takeaways",
            "blocked_shots",
            "pim",
            "faceoff_winning_pctg",
        ],
    ).to_pylist()
    events = group_by_game(pq.read_table(staging / "events.parquet", columns=EVENT_COLUMNS).to_pylist())

    player_rows, team_rows = [], []
    notes = Counter()
    stint_player_seconds = Counter()
    agree = Counter()
    for game_id, game_shifts in shifts.items():
        game = games[game_id]
        game_stints = stint_rows(game, build_stints(game, game_shifts))
        for stint in game_stints:
            for side in SIDES:
                stint_player_seconds[stint[f"{side}_strength"]] += stint["seconds"] * len(stint[f"{side}_skater_ids"])
        players, teams, game_notes = base_tables.build_game_tables(
            game, game_stints, attempts.get(game_id, []), events.get(game_id, [])
        )
        player_rows.extend(players)
        team_rows.extend(teams)
        notes.update(game_notes)
        index = StintIndex(game_stints)
        for attempt in attempts.get(game_id, []):
            if not attempt["has_on_ice"]:
                continue
            stint = index.at(attempt["game_seconds"], end_inclusive=attempt["attempt_type"] == "goal")
            if stint is None:
                continue
            shooting = "home" if attempt["is_home"] else "away"
            other = "away" if shooting == "home" else "home"
            agree["compared"] += 1
            agree["same"] += sorted(stint[f"{shooting}_skater_ids"]) == sorted(attempt["skater_ids_for"]) and sorted(
                stint[f"{other}_skater_ids"]
            ) == sorted(attempt["skater_ids_against"])

    missing = len(games) - len(shifts)
    print(f"Season {args.season}: {len(shifts)} games with stints, {missing} without shift data")
    print(f"Rows: {len(player_rows)} player rows, {len(team_rows)} team rows")

    base_seconds = Counter()
    for row in player_rows:
        base_seconds[row["strength"]] += row["seconds"]
    print(
        "\n1. Player seconds in the rows equal the stints' player-seconds: "
        f"{all(base_seconds[s] == stint_player_seconds[s] for s in STRENGTHS)}  "
        + ", ".join(f"{s} {base_seconds[s]}" for s in STRENGTHS)
    )

    if missing:
        print("\n2. Skipped: the NHL's season totals include games we have no shifts for.")
    else:
        reference_path = RAW_ROOT / f"season={args.season}" / "reference" / "skater_timeonice.json.gz"
        with gzip.open(reference_path, "rb") as handle:
            reference = {r["playerId"]: r for r in json.loads(handle.read())["data"]}
        per_player = Counter()
        for row in player_rows:
            per_player[(row["player_id"], row["strength"])] += row["seconds"]
        print(f"\n2. Time on ice by strength vs the NHL ({len(reference)} skaters)")
        for strength in STRENGTHS:
            field = REFERENCE_FIELDS[strength]
            ours = sum(per_player.get((p, strength), 0) for p in reference)
            nhl = sum(r[field] for r in reference.values())
            over = sum(1 for p, r in reference.items() if abs(per_player.get((p, strength), 0) - r[field]) > 60)
            print(
                f"   {strength}: ours {ours}, NHL {nhl}, {100 * (ours - nhl) / nhl:+.2f}%; "
                f"{over} skaters off by more than 60 s"
            )

    ours_pm, ours_goals, ours_sog, ours_ppg = Counter(), Counter(), Counter(), Counter()
    for row in player_rows:
        key = (row["game_id"], row["player_id"])
        ours_pm[key] += base_tables.plus_minus(row)
        ours_goals[key] += row["ind_goal"]
        ours_sog[key] += row["ind_goal"] + row["ind_sog"]
        if row["strength"] == "pp":
            ours_ppg[key] += row["ind_goal"]
    skaters = [b for b in box if b["player_group"] != "goalies" and b["game_id"] in shifts]
    print("\n3-4. Per player per game against the boxscore")
    for title, ours, column in (
        ("plus/minus", ours_pm, "plus_minus"),
        ("goals", ours_goals, "goals"),
        ("shots on goal", ours_sog, "sog"),
        ("power-play goals", ours_ppg, "power_play_goals"),
    ):
        compare(title, ours, {(b["game_id"], b["player_id"]): b[column] for b in skaters if b[column] is not None})

    counted = {kind: 0 for kind in base_tables.KINDS}
    against = dict(counted)
    for row in team_rows:
        for kind in base_tables.KINDS:
            counted[kind] += row[f"for_{kind}"]
            against[kind] += row[f"against_{kind}"]
    inside = Counter(
        base_tables.KIND_BY_ATTEMPT[a["attempt_type"]] for game_id in shifts for a in attempts.get(game_id, [])
    )
    print("\n5. Attempts in the team rows, for / against / all attempts in games with stints")
    for kind in base_tables.KINDS:
        print(f"   {kind}: {counted[kind]} / {against[kind]} / {inside[kind]}")
    print(
        f"   attempts outside every stint (not counted): {notes['attempts_outside_stints']}; "
        f"shooter not on the ice in his stint (credited anyway): {notes['shooter_not_on_ice']}; "
        f"goalie as shooter (no skater row): {notes['goalie_shooter']}"
    )

    print(
        f"\n6. Skaters on the ice at each attempt, stint vs Phase 3: {agree['same']} of {agree['compared']} "
        f"the same ({100 * agree['same'] / agree['compared']:.2f}%)"
    )

    per_player_game = Counter((r["game_id"], r["player_id"]) for r in player_rows)
    print(
        f"\n7. Rows per player-game: mean {sum(per_player_game.values()) / len(per_player_game):.2f}, "
        f"max {max(per_player_game.values())}"
    )
    state_seconds = Counter()
    for row in team_rows:
        state_seconds[tuple(row[c] for c in base_tables.STATE_COLUMNS)] += row["seconds"]
    total = sum(state_seconds.values())
    print("   Largest states by team-seconds (strength, skaters for v against, goalies for v against):")
    for state, seconds in state_seconds.most_common(10):
        print(f"   {state[0]} {state[1]}v{state[2]}, goalies {state[3]}v{state[4]}: {100 * seconds / total:.2f}%")

    print("\n8. Other counting stats per player per game against the boxscore")
    totals = defaultdict(Counter)
    for row in player_rows:
        key = (row["game_id"], row["player_id"])
        for column in (
            "assists_primary",
            "assists_secondary",
            "hits_made",
            "giveaways",
            "takeaways",
            "blocks_made",
            "penalty_minutes",
            "faceoff_wins",
            "faceoff_losses",
        ):
            totals[column][key] += row[column]
    ours_assists = Counter(
        {
            k: totals["assists_primary"][k] + totals["assists_secondary"][k]
            for k in set(totals["assists_primary"]) | set(totals["assists_secondary"])
        }
    )
    for title, ours, column in (
        ("assists", ours_assists, "assists"),
        ("hits", totals["hits_made"], "hits"),
        ("giveaways", totals["giveaways"], "giveaways"),
        ("takeaways", totals["takeaways"], "takeaways"),
        ("blocked shots", totals["blocks_made"], "blocked_shots"),
        ("penalty minutes", totals["penalty_minutes"], "pim"),
    ):
        compare(title, ours, {(b["game_id"], b["player_id"]): b[column] for b in skaters if b[column] is not None})

    close, near, far, no_faceoffs = 0, 0, 0, 0
    worst = []
    for b in skaters:
        official = b["faceoff_winning_pctg"]
        key = (b["game_id"], b["player_id"])
        taken = totals["faceoff_wins"][key] + totals["faceoff_losses"][key]
        if official is None or not taken:
            no_faceoffs += official not in (None, 0) and not taken
            continue
        official = official / 100 if official > 1 else official
        gap = abs(totals["faceoff_wins"][key] / taken - official)
        close += gap <= 0.001
        near += 0.001 < gap <= 0.01
        far += gap > 0.01
        worst.append((gap, key))
    print(
        f"   faceoff win % within 0.1 point: {close}, within 1 point: {near}, further off: {far}; "
        f"boxscore has a percentage but we have no faceoffs: {no_faceoffs}"
    )
    for gap, (game_id, player_id) in sorted(worst, reverse=True)[:3]:
        print(f"      {game_id} {player_id} off by {gap:.3f}")

    print("   Event owner team vs the team the player is on (players who were on the ice):")
    for column in (
        "assists_primary",
        "assists_secondary",
        "hits_made",
        "hits_taken",
        "giveaways",
        "takeaways",
        "faceoff_wins",
        "faceoff_losses",
        "penalties_taken",
        "penalties_drawn",
    ):
        same, differs = notes[f"{column}:team_matches_owner"], notes[f"{column}:team_differs_from_owner"]
        if same + differs:
            print(f"      {column}: {100 * same / (same + differs):.2f}% agree of {same + differs}")
    print(
        f"   goalies named in events (no skater row): {notes['goalie_event']}; "
        f"players not on the ice, placed by the owner team: {notes['actor_not_on_ice']}; "
        f"unplaceable: {notes['actor_unplaceable']}; events outside every stint: {notes['events_outside_stints']}"
    )


if __name__ == "__main__":
    main()
