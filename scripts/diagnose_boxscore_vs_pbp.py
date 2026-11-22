"""Verify the goalie shifts and find why the boxscore differs from the play-by-play.

Run from the repo root with the `nhl` conda environment active:

    python scripts/diagnose_boxscore_vs_pbp.py --season 2025

A. Goalie shifts. Every goal and shot on goal in the play-by-play names the goalie in net. For each,
   is that goalie on the ice at that second in our stints? Counts by status, and for the cases where
   he is not, his raw and cleaned shifts around the event (to see whether the NHL's chart lacks the
   shift or our cleaning dropped it).
B. Skaters' shots. The boxscore's shots on goal for each skater and game against the number of shot
   and goal events he took. Where they differ, what the events have in common (compared with the
   skater-games that agree). A shot by a goalie is not in a skater's row, so it is counted apart.
C. Goalies' shots against. The boxscore's shots against for each goalie and game against the events
   that name him, and what the events in the differing games have in common.
Features of an event: another shot by the same shooter within 2 s (a duplicate or a rebound), within
1 s after a goal, no shot type, no coordinates, overtime, the last 10 s of a period, a shooter who
is a goalie, a named goalie who plays for the shooter's own team.
Writes data/logs/boxscore_vs_pbp_<season>.csv with the events of every differing player-game.
Shootout events are left out.
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

from stints import StintIndex  # noqa: E402

STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"
LOG_DIR = REPO_ROOT / "data" / "logs"
SHOT_TYPES = ("goal", "shot-on-goal")
EVENT_COLUMNS = [
    "game_id",
    "event_id",
    "event_type",
    "period",
    "period_type",
    "game_seconds",
    "seconds_remaining_in_period",
    "event_owner_team_id",
    "shooting_player_id",
    "scoring_player_id",
    "goalie_in_net_id",
    "shot_type",
    "x_coord",
    "y_coord",
]
BOX_COLUMNS = ["game_id", "team_id", "player_group", "player_id", "sog", "shots_against"]
FEATURES = (
    "duplicate_within_2s",
    "within_1s_after_goal",
    "no_shot_type",
    "no_coordinates",
    "overtime",
    "last_10s_of_period",
    "shooter_is_goalie",
    "goalie_on_shooters_team",
)
SHIFT_WINDOW = 300


def shooter_of(event):
    return event["scoring_player_id"] if event["event_type"] == "goal" else event["shooting_player_id"]


def shot_events(events):
    return [e for e in events if e["event_type"] in SHOT_TYPES and e["period_type"] != "SO"]


def annotate(events, goalie_team):
    """Shot events of one game with the FEATURES flags. `goalie_team` maps a goalie id to his team id."""
    shots = shot_events(events)
    goals = [e for e in events if e["event_type"] == "goal" and e["period_type"] != "SO"]
    rows = []
    for event in shots:
        shooter = shooter_of(event)
        time = event["game_seconds"]
        flags = {
            "duplicate_within_2s": any(
                other is not event
                and other["event_owner_team_id"] == event["event_owner_team_id"]
                and shooter_of(other) == shooter
                and abs(other["game_seconds"] - time) <= 2
                for other in shots
            ),
            "within_1s_after_goal": any(g is not event and 0 <= time - g["game_seconds"] <= 1 for g in goals),
            "no_shot_type": event["shot_type"] is None,
            "no_coordinates": event["x_coord"] is None or event["y_coord"] is None,
            "overtime": event["period_type"] == "OT",
            "last_10s_of_period": (
                event["seconds_remaining_in_period"] is not None and event["seconds_remaining_in_period"] <= 10
            ),
            "shooter_is_goalie": shooter in goalie_team,
            "goalie_on_shooters_team": (
                event["goalie_in_net_id"] is not None
                and goalie_team.get(event["goalie_in_net_id"]) == event["event_owner_team_id"]
            ),
        }
        rows.append({"event": event, "shooter": shooter, **flags})
    return rows


def goalie_shift_status(game, events, stints):
    """One dict per shot or goal that names a goalie: is that goalie on the ice in our stints?"""
    side_of = {game["home_team_id"]: "home", game["away_team_id"]: "away"}
    index = StintIndex(stints)
    results = []
    for event in shot_events(events):
        goalie = event["goalie_in_net_id"]
        owner = event["event_owner_team_id"]
        if goalie is None or owner not in side_of:
            continue
        defending = "away" if side_of[owner] == "home" else "home"
        stint = index.at(event["game_seconds"], end_inclusive=event["event_type"] == "goal")
        if stint is None:
            status, on_ice = "outside our stints", []
        else:
            on_ice = stint[f"{defending}_goalie_ids"]
            status = (
                "named goalie on the ice"
                if goalie in on_ice
                else ("no goalie on the ice" if not on_ice else "a different goalie on the ice")
            )
        results.append(
            {
                "game_id": game["game_id"],
                "event_id": event["event_id"],
                "game_seconds": event["game_seconds"],
                "goalie_id": goalie,
                "team_id": game[f"{defending}_team_id"],
                "status": status,
                "on_ice": list(on_ice),
            }
        )
    return results


def compare_counts(counts, box):
    """[(key, box, events)] for every key in either dict where they differ."""
    return [
        (key, box.get(key, 0), counts.get(key, 0))
        for key in sorted(set(counts) | set(box))
        if counts.get(key, 0) != box.get(key, 0)
    ]


def percent(part, whole):
    return f"{100 * part / whole:5.1f}%" if whole else "  n/a"


def print_features(title, differing, agreeing):
    """Share of differing and of agreeing player-games with at least one event with each feature."""
    print(f"  {title}: features of the events (share of games with at least one event with the feature)")
    print(f"    {'feature':26s}{'differing':>12s}{'agreeing':>12s}")
    for feature in FEATURES:
        mine = sum(1 for flags in differing if flags[feature])
        base = sum(1 for flags in agreeing if flags[feature])
        print(f"    {feature:26s}{percent(mine, len(differing)):>12s}{percent(base, len(agreeing)):>12s}")


def process_game(game, events, stints, box):
    """Everything the report needs from one game.

    shift_results: goalie_shift_status rows (only when the game has stints).
    skater_diffs / goalie_diffs: (game_id, player_id, boxscore, events, annotated events) where they differ.
    skater_agree / goalie_agree: the annotated events of players where they agree.
    reconcile: counts that split the game's shot events by who took them.
    """
    goalie_team = {r["player_id"]: r["team_id"] for r in box if r["player_group"] == "goalies"}
    annotated = annotate(events, goalie_team)
    by_shooter, by_goalie = defaultdict(list), defaultdict(list)
    for item in annotated:
        by_shooter[item["shooter"]].append(item)
        if item["event"]["goalie_in_net_id"] is not None:
            by_goalie[item["event"]["goalie_in_net_id"]].append(item)
    skater_box = {r["player_id"]: r["sog"] or 0 for r in box if r["player_group"] != "goalies"}
    goalie_box = {r["player_id"]: r["shots_against"] or 0 for r in box if r["player_group"] == "goalies"}

    reconcile = Counter()
    reconcile["events"] = len(annotated)
    reconcile["by_goalies"] = sum(1 for item in annotated if item["shooter"] in goalie_team)
    reconcile["no_shooter"] = sum(1 for item in annotated if item["shooter"] is None)
    reconcile["not_in_boxscore"] = sum(
        1
        for item in annotated
        if item["shooter"] is not None and item["shooter"] not in skater_box and item["shooter"] not in goalie_team
    )
    reconcile["box_skater_shots"] = sum(skater_box.values())

    out = {"shift_results": goalie_shift_status(game, events, stints) if stints else [], "reconcile": reconcile}
    for name, grouped, box_counts in (("skater", by_shooter, skater_box), ("goalie", by_goalie, goalie_box)):
        counts = {player: len(items) for player, items in grouped.items() if player in box_counts}
        differing = compare_counts(counts, box_counts)
        different_players = {player for player, _, _ in differing}
        out[f"{name}_diffs"] = [(game["game_id"], player, b, e, grouped.get(player, [])) for player, b, e in differing]
        out[f"{name}_agree"] = [grouped[p] for p in box_counts if p not in different_players and grouped.get(p)]
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Verify goalie shifts; find why the boxscore differs from the play-by-play."
    )
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    staging = STAGING_ROOT / f"season={args.season}"
    metrics = METRICS_ROOT / f"season={args.season}"

    games = {
        g["game_id"]: g
        for g in pq.read_table(
            staging / "games.parquet", columns=["game_id", "game_type", "has_boxscore", "home_team_id", "away_team_id"]
        ).to_pylist()
        if g["game_type"] == 2 and g["has_boxscore"]
    }
    events_by_game, stints_by_game, box_by_game = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in pq.read_table(staging / "events.parquet", columns=EVENT_COLUMNS).to_pylist():
        events_by_game[row["game_id"]].append(row)
    for row in pq.read_table(metrics / "stints.parquet").to_pylist():
        stints_by_game[row["game_id"]].append(row)
    for row in pq.read_table(staging / "boxscore_players.parquet", columns=BOX_COLUMNS).to_pylist():
        box_by_game[row["game_id"]].append(row)

    shift_results = []
    skater_diffs, goalie_diffs, skater_agree, goalie_agree = [], [], [], []
    reconcile = Counter()
    for game_id, game in games.items():
        stints = sorted(stints_by_game.get(game_id, []), key=lambda r: r["start_game_seconds"])
        result = process_game(game, events_by_game[game_id], stints, box_by_game[game_id])
        shift_results.extend(result["shift_results"])
        skater_diffs.extend(result["skater_diffs"])
        goalie_diffs.extend(result["goalie_diffs"])
        skater_agree.extend(result["skater_agree"])
        goalie_agree.extend(result["goalie_agree"])
        reconcile.update(result["reconcile"])
    print(f"Season {args.season}: {len(games)} games")

    print("\nA. Goalie shifts: is the goalie the play-by-play names on the ice in our stints?")
    statuses = Counter(r["status"] for r in shift_results)
    for status, n in statuses.most_common():
        print(f"  {status}: {n} of {len(shift_results)} ({percent(n, len(shift_results)).strip()})")
    bad = [r for r in shift_results if r["status"] != "named goalie on the ice"]
    if bad:
        shifts_raw = pq.read_table(
            staging / "shifts.parquet",
            columns=[
                "game_id",
                "player_id",
                "team_id",
                "period",
                "shift_number",
                "start_game_seconds",
                "end_game_seconds",
            ],
            filters=[("game_id", "in", sorted({r["game_id"] for r in bad}))],
        ).to_pylist()
        clean_path = INTERMEDIATE_ROOT / f"season={args.season}" / "shifts_clean.parquet"
        kept = {
            (r["game_id"], r["player_id"], r["start_game_seconds"], r["end_game_seconds"])
            for r in pq.read_table(
                clean_path,
                columns=["game_id", "player_id", "start_game_seconds", "end_game_seconds"],
                filters=[("game_id", "in", sorted({r["game_id"] for r in bad}))],
            ).to_pylist()
        }
        print(
            f"\n  The {len(bad)} cases, with the named goalie's shifts in the game within {SHIFT_WINDOW} s of the shot"
        )
        print("  (shift: start-end in game seconds; '*' = in the NHL's raw chart but dropped by our cleaning)")
        for r in sorted(bad, key=lambda r: (r["game_id"], r["game_seconds"]))[:20]:
            near = sorted(
                (
                    s
                    for s in shifts_raw
                    if s["game_id"] == r["game_id"]
                    and s["player_id"] == r["goalie_id"]
                    and s["start_game_seconds"] - SHIFT_WINDOW
                    <= r["game_seconds"]
                    <= s["end_game_seconds"] + SHIFT_WINDOW
                ),
                key=lambda s: s["start_game_seconds"],
            )
            text = (
                ", ".join(
                    f"{s['start_game_seconds']}-{s['end_game_seconds']}"
                    + (
                        ""
                        if (s["game_id"], s["player_id"], s["start_game_seconds"], s["end_game_seconds"]) in kept
                        else "*"
                    )
                    for s in near
                )
                or "none in the raw chart"
            )
            print(
                f"    game {r['game_id']} at {r['game_seconds']} s, goalie {r['goalie_id']}: {r['status']} (on ice: {r['on_ice']}); his shifts: {text}"
            )

    print("\nB. Skaters' shots: boxscore shots on goal vs shot and goal events by the skater")
    print(
        f"  events {reconcile['events']} = by goalies {reconcile['by_goalies']} + with no shooter {reconcile['no_shooter']} "
        f"+ by someone not in the boxscore {reconcile['not_in_boxscore']} + by skaters {reconcile['events'] - reconcile['by_goalies'] - reconcile['no_shooter'] - reconcile['not_in_boxscore']}"
    )
    print(f"  boxscore skaters' shots on goal: {reconcile['box_skater_shots']}")
    print(
        f"  skater-games that differ: {len(skater_diffs)}; difference (events - boxscore) over them: "
        + ", ".join(f"{d:+d} x {n}" for d, n in sorted(Counter(e - b for _, _, b, e, _ in skater_diffs).items()))
    )
    print_features(
        "skaters", [flags_of(items) for *_, items in skater_diffs], [flags_of(items) for items in skater_agree]
    )

    print("\nC. Goalies' shots against: boxscore vs events that name the goalie")
    print(
        f"  goalie-games that differ: {len(goalie_diffs)}; difference (events - boxscore): "
        + ", ".join(f"{d:+d} x {n}" for d, n in sorted(Counter(e - b for _, _, b, e, _ in goalie_diffs).items()))
    )
    print_features(
        "goalies", [flags_of(items) for *_, items in goalie_diffs], [flags_of(items) for items in goalie_agree]
    )

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = LOG_DIR / f"boxscore_vs_pbp_{args.season}.csv"
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "table",
                "game_id",
                "player_id",
                "boxscore",
                "events",
                "event_id",
                "game_seconds",
                "event_type",
                "period_type",
                *FEATURES,
            ]
        )
        for table, rows in (("skater", skater_diffs), ("goalie", goalie_diffs)):
            for game_id, player, box_value, event_value, items in rows:
                for item in items:
                    event = item["event"]
                    writer.writerow(
                        [
                            table,
                            game_id,
                            player,
                            box_value,
                            event_value,
                            event["event_id"],
                            event["game_seconds"],
                            event["event_type"],
                            event["period_type"],
                            *(int(item[f]) for f in FEATURES),
                        ]
                    )
    print(f"\nEvents of every differing player-game written to {out}")
    print("\nExamples (first 5 differing goalie-games and skater-games):")
    for label, rows in (("goalie", goalie_diffs), ("skater", skater_diffs)):
        for game_id, player, box_value, event_value, items in rows[:5]:
            print(f"  {label} {player} game {game_id}: boxscore {box_value}, events {event_value}")
            for item in sorted(items, key=lambda i: i["event"]["game_seconds"]):
                on = [f for f in FEATURES if item[f]]
                print(
                    f"    {item['event']['game_seconds']:5d} s {item['event']['event_type']:12s} {item['event']['period_type']:4s} "
                    + (", ".join(on) or "-")
                )


def flags_of(items):
    """For a game's events of one player: which FEATURES at least one event has."""
    return {feature: any(item[feature] for item in items) for feature in FEATURES}


if __name__ == "__main__":
    main()
