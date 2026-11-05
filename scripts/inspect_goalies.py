"""Look at the goalie rows of the boxscore staging table, before building goalie season stats.

Run from the repo root with the `nhl` conda environment active:

    python scripts/inspect_goalies.py --season 2025

Read-only. Prints which columns the goalie rows have (and how many are filled), three sample rows,
the values of the decision and starter columns, and how many goalie-games have time on ice.
"""

import argparse
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"


def main():
    parser = argparse.ArgumentParser(description="Inspect the goalie rows of the boxscore table.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    path = (STAGING_ROOT / f"season={args.season}" / "boxscore_players.parquet").as_posix()

    con = duckdb.connect()
    con.execute(f"create temp view goalies as select * from '{path}' where player_group = 'goalies'")
    columns = [row[0] for row in con.execute("describe goalies").fetchall()]
    total = con.execute("select count(*) from goalies").fetchone()[0]
    print(f"Season {args.season}: {total} goalie rows\n")

    print("Columns: name, type, filled rows")
    for name, kind, *_ in con.execute("describe goalies").fetchall():
        filled = con.execute(f'select count("{name}") from goalies').fetchone()[0]
        print(f"  {name:36s} {kind:12s} {filled}")

    print("\nThree sample rows (one column per line)")
    sample = con.execute("select * from goalies where toi_seconds > 0 order by game_id limit 3").fetchall()
    for row in sample:
        print("  ---")
        for name, value in zip(columns, row):
            print(f"  {name:36s} {value}")

    for column in ("decision", "starter"):
        if column in columns:
            print(f"\nValues of {column}")
            con.sql(f'select "{column}" as value, count(*) as rows from goalies group by 1 order by 2 desc').show()

    print("Goalie rows with time on ice, and with none")
    con.sql(
        "select count(*) filter (where toi_seconds > 0) as with_toi, "
        "count(*) filter (where toi_seconds = 0 or toi_seconds is null) as without_toi from goalies"
    ).show()


if __name__ == "__main__":
    main()