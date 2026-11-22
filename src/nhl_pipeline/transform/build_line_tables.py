"""Phase 6: build the forward line and defense pair tables for one season.

Run from the repo root with the `nhl` conda environment active, after build_stints.py and build_base_tables.py:

    python src/nhl_pipeline/transform/build_line_tables.py --season 2025

Reads  data/staging/season=2025/{games,boxscore_players}.parquet
       data/metrics/season=2025/{stints,shot_attempts,team_game_strength}.parquet
Writes data/metrics/season=2025/unit_game_5v5.parquet     one row per game, team and unit (line or pair)
       data/metrics/season=2025/unit_season_5v5.parquet   one row per team and unit, summed over the season

A line is 3 forwards and a pair 2 defensemen on the ice together at 5v5 (see line_tables.py for the rules). It prints
how long the units played together, so the minimum time to show a unit can be chosen from the data, and how much of
each team's 5v5 time and attempts the lines and pairs account for.
"""

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from line_tables import (
    COUNT_COLUMNS,
    UNIT_TYPES,
    build_game_unit_rows,
    describe_units,
    is_five_on_five,
    positions_by_game,
    season_unit_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
ATTEMPT_COLUMNS = [
    "game_id",
    "event_id",
    "game_seconds",
    "attempt_type",
    "is_home",
    "skaters_for",
    "skaters_against",
    "goalie_for",
    "goalie_against",
]
GAME_SCHEMA = pa.schema(
    [
        ("season", pa.int64()),
        ("game_id", pa.int64()),
        ("team_id", pa.int64()),
        ("unit_type", pa.string()),
        ("player_ids", pa.list_(pa.int64())),
    ]
    + [(name, pa.int64()) for name in COUNT_COLUMNS]
)
SEASON_FIELDS = (
    [
        ("season", pa.int64()),
        ("team_id", pa.int64()),
        ("unit_type", pa.string()),
        ("player_ids", pa.list_(pa.int64())),
        ("games", pa.int64()),
        ("seconds", pa.int64()),
    ]
    + [(name, pa.int64()) for name in ("cf", "ca", "ff", "fa", "sf", "sa", "gf", "ga")]
    + [
        (name, pa.float64())
        for name in (
            "cf_pct",
            "ff_pct",
            "sf_pct",
            "gf_pct",
            "sh_pct",
            "sv_pct",
            "pdo",
            "cf_per_60",
            "ca_per_60",
            "gf_per_60",
            "ga_per_60",
        )
    ]
)
SEASON_SCHEMA = pa.schema(SEASON_FIELDS)


def group_by_game(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["game_id"]].append(row)
    return groups


def main():
    parser = argparse.ArgumentParser(description="Build the line and pair tables for one season.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    staging = args.staging_root / f"season={args.season}"
    metrics = args.metrics_root / f"season={args.season}"
    games = {
        g["game_id"]: g
        for g in pq.read_table(
            staging / "games.parquet", columns=["game_id", "home_team_id", "away_team_id"]
        ).to_pylist()
    }
    positions = positions_by_game(
        pq.read_table(
            staging / "boxscore_players.parquet", columns=["game_id", "player_id", "position", "player_group"]
        ).to_pylist()
    )
    stints = group_by_game(pq.read_table(metrics / "stints.parquet").to_pylist())
    attempts = group_by_game(pq.read_table(metrics / "shot_attempts.parquet", columns=ATTEMPT_COLUMNS).to_pylist())

    game_rows = []
    for game_id in sorted(stints):
        game_rows.extend(
            build_game_unit_rows(games[game_id], stints[game_id], attempts.get(game_id, []), positions.get(game_id, {}))
        )
    for row in game_rows:
        row["season"] = args.season
    season_rows = season_unit_rows(game_rows)
    for row in season_rows:
        row["season"] = args.season

    metrics.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(game_rows, schema=GAME_SCHEMA), metrics / "unit_game_5v5.parquet", compression="zstd"
    )
    pq.write_table(
        pa.Table.from_pylist(season_rows, schema=SEASON_SCHEMA), metrics / "unit_season_5v5.parquet", compression="zstd"
    )
    print(f"Season {args.season}: {len(stints)} games, {len(game_rows)} game rows, {len(season_rows)} season rows")
    print(f"Written to {metrics}")

    print("\nMinutes together at 5v5 (all units, then how many reach each minimum):")
    for unit_type, info in describe_units(season_rows).items():
        reach = ", ".join(
            f"{t}+ min: {info['at_least'][t]} ({info['per_team'][t]:.1f} per team)" for t in info["at_least"]
        )
        print(
            f"  {unit_type:5s} {info['units']:5d} units  median {info['median']:.1f}  mean {info['mean']:.1f}  "
            f"90th percentile {info['p90']:.1f}  max {info['max']:.1f}\n        {reach}"
        )

    team_seconds, team_cf = Counter(), Counter()
    for row in pq.read_table(metrics / "team_game_strength.parquet").to_pylist():
        if row["strength"] == "ev" and is_five_on_five(
            (row["strength"], row["skaters_for"], row["skaters_against"], row["goalies_for"], row["goalies_against"])
        ):
            team_seconds[row["team_id"]] += row["seconds"]
            team_cf[row["team_id"]] += sum(row[f"for_{k}"] for k in ("goal", "sog", "miss", "block"))
    for unit_type in UNIT_TYPES:
        covered_seconds, covered_cf = Counter(), Counter()
        for row in season_rows:
            if row["unit_type"] == unit_type:
                covered_seconds[row["team_id"]] += row["seconds"]
                covered_cf[row["team_id"]] += row["cf"]
        share = 100 * sum(covered_seconds.values()) / sum(team_seconds.values())
        share_cf = 100 * sum(covered_cf.values()) / sum(team_cf.values())
        exact = "3 forwards" if unit_type == "line" else "2 defensemen"
        print(
            f"\nTeam 5v5 time on ice in a {unit_type} ({exact} exactly): {share:.1f}%"
            f"; of the team's 5v5 Corsi for: {share_cf:.1f}%"
        )
        top = sorted((r for r in season_rows if r["unit_type"] == unit_type), key=lambda r: -r["seconds"])[:5]
        print(
            f"Most time together ({unit_type}): "
            + "; ".join(
                f"team {r['team_id']} {r['player_ids']} {r['seconds'] / 60:.0f} min CF% {r['cf_pct']:.1f}" for r in top
            )
        )


if __name__ == "__main__":
    main()
