"""Phase 7: how much 5v5 ice time do skaters have? Used to choose the minimum for the comparison pool.

Run from the repo root with the `nhl` conda environment active, after build_player_advanced.py and
build_season_display.py:

    python scripts/diagnose_skater_minutes.py

For each season it groups skaters as forwards (C, L, R) or defensemen (D) and prints, for the 5v5 minutes (one row per
player: the combined row of a traded player, else his only row), the median and mean, the 90th percentile, and how many
skaters reach each minimum (200 to 1,000 minutes), with the games that minimum is at the player's own pace. It also prints
the median time on ice per game (all situations) of the skaters at each minimum.
"""

import argparse
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
FORWARDS = {"C", "L", "R", "LW", "RW", "F"}
THRESHOLDS = (200, 300, 400, 500, 600, 800, 1000)
SEASONS = (2023, 2024, 2025)


def one_row_per_player(rows):
    """The combined ('total') row of a traded player, else his only row."""
    chosen = {}
    for row in rows:
        current = chosen.get(row["player_id"])
        if current is None or (row.get("kind") == "total" and current.get("kind") != "total"):
            chosen[row["player_id"]] = row
    return list(chosen.values())


def position_group(position):
    if position == "D":
        return "D"
    return "F" if position in FORWARDS else None


def describe_minutes(minutes, thresholds=THRESHOLDS):
    """{'skaters', 'median', 'mean', 'p90', 'at_least': {minimum: skaters reaching it}} for a list of minutes."""
    ordered = sorted(minutes)
    if not ordered:
        return {"skaters": 0, "median": None, "mean": None, "p90": None, "at_least": {t: 0 for t in thresholds}}
    return {
        "skaters": len(ordered), "median": statistics.median(ordered), "mean": statistics.fmean(ordered),
        "p90": ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))],
        "at_least": {t: sum(1 for m in ordered if m >= t) for t in thresholds},
    }


def main():
    parser = argparse.ArgumentParser(description="5v5 minutes of skaters, to choose the comparison pool's minimum.")
    parser.add_argument("--metrics-root", type=Path, default=METRICS_ROOT)
    args = parser.parse_args()

    import pyarrow.parquet as pq

    for season in SEASONS:
        folder = args.metrics_root / f"season={season}"
        advanced = pq.read_table(folder / "player_season_advanced.parquet")
        for needed in ("player_id", "situation", "seconds"):
            if needed not in advanced.column_names:
                sys.exit(f"player_season_advanced has no column {needed!r}; columns are {advanced.column_names}")
        display = {r["player_id"]: r for r in one_row_per_player(
            pq.read_table(folder / "player_season_display.parquet").to_pylist())}
        five = [r for r in advanced.to_pylist() if r["situation"] == "5v5"]
        by_group = {"F": [], "D": []}
        for row in one_row_per_player(five):
            shown = display.get(row["player_id"])
            group = position_group(shown["position"]) if shown else None
            if group:
                by_group[group].append((row["seconds"] / 60, shown["toi_per_game_seconds"] / 60 if shown["toi_per_game_seconds"] else 0))
        print(f"\nseason {season}")
        for group, label in (("F", "forwards"), ("D", "defensemen")):
            minutes = [m for m, _ in by_group[group]]
            d = describe_minutes(minutes)
            print(f"  {label}: {d['skaters']} skaters, 5v5 minutes median {d['median']:.0f}, mean {d['mean']:.0f}, 90th pct {d['p90']:.0f}")
            for t in THRESHOLDS:
                reaching = [toi for m, toi in by_group[group] if m >= t]
                median_toi = f"{statistics.median(reaching):.1f}" if reaching else "-"
                print(f"    at least {t:>4} min: {d['at_least'][t]:>4} skaters (median TOI/game of these {median_toi})")


if __name__ == "__main__":
    main()