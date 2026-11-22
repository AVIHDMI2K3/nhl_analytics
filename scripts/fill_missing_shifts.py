"""Fill games the shift-chart API has no shifts for from the NHL's HTML time-on-ice reports (Phase 5).

For 2024-25, 57 games (shift_status 'none_from_nhl', ids 2024021235 to 2024021291) have no shifts from the API. The
HTML reports exist for them and agree exactly with the API on games that have both (scripts/compare_html_shifts.py).
This reads the reports of every such game, matches players to ids by jersey number through the boxscore, and checks
each player's total shift time against the boxscore's time on ice. With --write it then:

  * appends the shifts to data/staging/season=<season>/shifts.parquet (shift_id is empty: the report has none),
  * sets those games' shift_status to 'ok' and records shift_source = 'html_report' (every other game: 'api'),
  * keeps the first version of both files next to them as shifts.parquet.bak and games.parquet.bak.

Without --write it only reports (and saves the pages in data/scratch), so look at that first. A game with a player the
boxscore cannot match, or whose times differ from the boxscore by more than 2 seconds for any player, is not loaded
unless it is listed after --force. Run from the repo root with the `nhl` environment active:

    python scripts/fill_missing_shifts.py --season 2024                 # report only, about 6 minutes the first time
    python scripts/fill_missing_shifts.py --season 2024 --write

After --write, rebuild everything downstream of the shifts (README step 3 onward). Re-running staging replaces
games.parquet and shifts.parquet, so run this again afterwards.
"""

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from compare_html_shifts import fetch  # noqa: E402
from shift_reports import parse_report, shift_rows, to_staging_row, toi_differences  # noqa: E402

MISSING_STATUS = "none_from_nhl"


def build_game(game_id, players, team_ids, abbrevs, fetch_report):
    """(staging rows, problems) of one game. `players` are its boxscore_players rows; `fetch_report(side)` gives the
    HTML of the 'TH' or 'TV' report. problems lists players without an id and players whose total shift time differs
    from the boxscore by more than 2 seconds."""
    rows, unmatched = [], []
    for side, home_or_away in (("TH", "home"), ("TV", "away")):
        ids = {p["sweater_number"]: p["player_id"] for p in players if p["home_or_away"] == home_or_away}
        team_id = team_ids[home_or_away]
        found, missing = shift_rows(game_id, team_id, parse_report(fetch_report(side)), ids)
        rows += found
        unmatched += missing
    toi = {p["player_id"]: p["toi_seconds"] for p in players}
    return rows, {"unmatched": unmatched, "toi": toi_differences(rows, toi)}


def main():
    parser = argparse.ArgumentParser(description="Fill games with no API shifts from the NHL's HTML reports.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--write", action="store_true", help="change the staging tables (default: report only)")
    parser.add_argument("--force", type=int, nargs="*", default=[], help="load these games even with problems")
    parser.add_argument("--limit", type=int, help="only the first N missing games (a trial)")
    parser.add_argument("--pause", type=float, default=3.0)
    args = parser.parse_args()
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    staging = REPO_ROOT / "data" / "staging" / f"season={args.season}"
    games = pq.read_table(staging / "games.parquet")
    rows = games.to_pylist()
    missing = sorted(r["game_id"] for r in rows if r["shift_status"] == MISSING_STATUS)
    if args.limit:
        missing = missing[: args.limit]
    if not missing:
        print(f"Season {args.season}: no games with shift_status '{MISSING_STATUS}'. Nothing to do.")
        return
    print(
        f"Season {args.season}: {len(missing)} games without API shifts "
        f"({'will write' if args.write else 'report only'})"
    )

    shifts = pq.read_table(staging / "shifts.parquet")
    pairs = shifts.group_by("team_id").aggregate([("team", "min")]).to_pylist()
    abbrevs = {row["team_id"]: row["team_min"] for row in pairs}
    box = pq.read_table(
        staging / "boxscore_players.parquet",
        columns=["game_id", "team_id", "home_or_away", "player_id", "sweater_number", "toi_seconds"],
    )
    by_id = {r["game_id"]: r for r in rows}
    loaded, new_rows = [], []
    for game_id in missing:
        players = pc.filter(box, pc.equal(box["game_id"], game_id)).to_pylist()
        team_ids = {"home": by_id[game_id]["home_team_id"], "away": by_id[game_id]["away_team_id"]}
        game_rows, problems = build_game(
            game_id, players, team_ids, abbrevs, lambda side, g=game_id: fetch(g, side, args.pause)
        )
        bad = bool(problems["unmatched"] or problems["toi"])
        status = "PROBLEM" if bad else "ok"
        print(
            f"{game_id}: {len(game_rows):4d} shifts  {status}"
            + (f"  unmatched {problems['unmatched']}  toi differences {problems['toi'][:4]}" if bad else "")
        )
        if not bad or game_id in args.force:
            loaded.append(game_id)
            names = {t: abbrevs.get(t) for t in team_ids.values()}
            new_rows += [to_staging_row(r, names.get(r["team_id"]), args.season) for r in game_rows]
    print(f"\n{len(loaded)} of {len(missing)} games are clean, {len(new_rows)} shift rows")
    if not args.write:
        print("Report only. Run again with --write to change the staging tables.")
        return

    for name in ("shifts.parquet", "games.parquet"):
        backup = staging / (name + ".bak")
        if not backup.exists():
            shutil.copy2(staging / name, backup)
    keep = pc.invert(pc.is_in(shifts["game_id"], value_set=pa.array(loaded, pa.int64())))
    merged = pa.concat_tables([shifts.filter(keep), pa.Table.from_pylist(new_rows, schema=shifts.schema)])
    pq.write_table(merged, staging / "shifts.parquet", compression="zstd")

    loaded_set = set(loaded)
    for row in rows:
        previous = row.get("shift_source")
        if row["game_id"] in loaded_set:
            row["shift_status"], row["shift_source"] = "ok", "html_report"
        else:
            row["shift_source"] = previous or ("api" if row["shift_status"] == "ok" else None)
    schema = games.schema
    if "shift_source" not in schema.names:
        schema = schema.append(pa.field("shift_source", pa.string()))
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), staging / "games.parquet", compression="zstd")
    print(f"Wrote {len(new_rows)} shift rows and updated {len(loaded)} games in {staging}")


if __name__ == "__main__":
    main()
