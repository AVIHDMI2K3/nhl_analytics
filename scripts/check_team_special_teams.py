"""Check our team power-play and penalty-kill tables against the NHL's team reports.

Run from the repo root with the `nhl` conda environment active, after build_team_special_teams.py and
ingest_reference.py:

    python scripts/check_team_special_teams.py --season 2025

Per team and game (team_powerplay_games and team_penaltykill_games) it compares opportunities (ppOpportunities),
power-play goals (powerPlayGoalsFor), times shorthanded (timesShorthanded), goals against while shorthanded
(ppGoalsAgainst), shorthanded goals for (shGoalsFor) and against (shGoalsAgainst). Per team and season it
compares the same and the two percentages with the NHL's. Opportunities are our own count, so they may differ
from the NHL's in a few team-games; the goals should match exactly.
"""

import argparse
import gzip
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))

RAW_ROOT = REPO_ROOT / "data" / "raw"
METRICS_ROOT = REPO_ROOT / "data" / "metrics"
# our column -> (NHL report, NHL field)
FIELDS = {
    "pp_opportunities": ("power", "ppOpportunities"),
    "pp_goals": ("power", "powerPlayGoalsFor"),
    "sh_goals_against": ("power", "shGoalsAgainst"),
    "times_shorthanded": ("kill", "timesShorthanded"),
    "pk_goals_against": ("kill", "ppGoalsAgainst"),
    "sh_goals_for": ("kill", "shGoalsFor"),
}


def as_percent(value):
    """The NHL gives a percentage as a fraction (0.21) in some reports; return 0-100."""
    return None if value is None else (value * 100 if value <= 1.0 else value)


def compare(ours, nhl):
    """(exact, total, ours total, NHL total, worst difference) for {key: value} dicts."""
    diffs = [ours.get(key, 0) - value for key, value in nhl.items()]
    worst = max(diffs, key=abs, default=0)
    return sum(1 for d in diffs if d == 0), len(diffs), sum(ours.get(k, 0) for k in nhl), sum(nhl.values()), worst


def load(season, name):
    with gzip.open(RAW_ROOT / f"season={season}" / "reference" / f"{name}.json.gz", "rb") as handle:
        return json.loads(handle.read())["data"]


def main():
    parser = argparse.ArgumentParser(description="Check the team power-play and penalty-kill tables.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    metrics = METRICS_ROOT / f"season={args.season}"
    game_rows = pq.read_table(metrics / "team_game_special_teams.parquet").to_pylist()
    season_rows = {r["team_id"]: r for r in pq.read_table(metrics / "team_season_special_teams.parquet").to_pylist()}
    ours = {(r["game_id"], r["team_id"]): r for r in game_rows}

    reports = {"power": load(args.season, "team_powerplay_games"), "kill": load(args.season, "team_penaltykill_games")}
    print(f"Season {args.season}: per team and game")
    for column, (report, field) in FIELDS.items():
        nhl = {(r["gameId"], r["teamId"]): r[field] for r in reports[report]}
        exact, total, mine, theirs, worst = compare({k: v[column] for k, v in ours.items()}, nhl)
        print(f"  {column:18s} ({field:18s}) exact {exact:4d}/{total}  ours {mine} NHL {theirs}  worst {worst:+d}")

    seasonal = {"power": load(args.season, "team_powerplay"), "kill": load(args.season, "team_penaltykill")}
    print(f"\nSeason {args.season}: per team")
    for column, (report, field) in FIELDS.items():
        nhl = {r["teamId"]: r[field] for r in seasonal[report]}
        exact, total, mine, theirs, worst = compare({k: v[column] for k, v in season_rows.items()}, nhl)
        print(f"  {column:18s} exact {exact:2d}/{total}  ours {mine} NHL {theirs}  worst {worst:+d}")
    for label, column, report, field in (
        ("power-play %", "pp_pct", "power", "powerPlayPct"), ("penalty-kill %", "pk_pct", "kill", "penaltyKillPct"),
    ):
        diffs = []
        for r in seasonal[report]:
            nhl_value, mine = as_percent(r.get(field)), season_rows[r["teamId"]][column]
            if nhl_value is not None and mine is not None:
                diffs.append((mine - nhl_value, season_rows[r["teamId"]]["team"]))
        worst = max(diffs, key=lambda d: abs(d[0]))
        print(f"  {label:15s} mean |difference| {sum(abs(d) for d, _ in diffs) / len(diffs):.2f} points, "
              f"worst {worst[0]:+.2f} ({worst[1]}), within 0.5 points for {sum(1 for d, _ in diffs if abs(d) <= 0.5)} of {len(diffs)} teams")


if __name__ == "__main__":
    main()