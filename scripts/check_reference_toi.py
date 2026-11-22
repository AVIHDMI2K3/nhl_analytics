"""Check our season time-on-ice totals against the NHL's own totals.

Run from the repo root with the `nhl` conda environment active, after
ingest_reference.py and build_onice.py:

    python scripts/check_reference_toi.py --season 2023

Read-only. For every skater it compares, over the regular season:
    total time on ice    sum of our cleaned shift lengths vs the NHL's timeOnIce (seconds)
    shifts               number of our cleaned shifts vs the NHL's shifts
    games played         games where we have a shift vs the NHL's gamesPlayed
Games with no NHL shift data (57 in 2024-25) are missing from our totals, so that
season is expected to show differences for players who played in them.

It also tests why the totals can differ: whether our extra shifts are the ones
flagged has_conflict, and whether merging overlapping shifts into one stretch
(so no second is counted twice) gives the NHL's total.
"""

import argparse
import gzip
import json
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data" / "raw"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"


def main():
    parser = argparse.ArgumentParser(description="Compare our time on ice with the NHL's totals.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    reference = RAW_ROOT / f"season={args.season}" / "reference" / "skater_timeonice.json.gz"
    with gzip.open(reference, "rb") as handle:
        body = json.loads(handle.read())
    shifts = (INTERMEDIATE_ROOT / f"season={args.season}" / "shifts_clean.parquet").as_posix()

    con = duckdb.connect()
    con.execute(
        "create temp table ref (player_id bigint, name varchar, games_played bigint, "
        "shifts bigint, toi bigint, ev bigint, pp bigint, sh bigint)"
    )
    con.executemany(
        "insert into ref values (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r["playerId"],
                r["skaterFullName"],
                r["gamesPlayed"],
                r["shifts"],
                r["timeOnIce"],
                r["evTimeOnIce"],
                r["ppTimeOnIce"],
                r["shTimeOnIce"],
            )
            for r in body["data"]
        ],
    )
    con.execute(
        f"""
        create temp table ours as
        select player_id,
               sum(end_game_seconds - start_game_seconds) as toi,
               count(*) as shifts,
               count(distinct game_id) as games_played,
               sum(has_conflict::integer) as flagged
        from '{shifts}'
        where not is_goalie
        group by 1
        """
    )
    con.execute(
        """
        create temp table cmp as
        select r.player_id, r.name,
               r.toi as nhl_toi, o.toi as our_toi, o.toi - r.toi as diff,
               r.shifts as nhl_shifts, o.shifts as our_shifts,
               r.games_played as nhl_gp, o.games_played as our_gp, o.flagged
        from ref as r join ours as o on o.player_id = r.player_id
        """
    )

    in_ref, matched = con.execute("select (select count(*) from ref), (select count(*) from cmp)").fetchone()
    print(f"Season {args.season}: {in_ref} skaters in the NHL's totals, {matched} found in our shifts\n")

    print("Total time on ice, ours minus the NHL's")
    con.sql(
        """
        select case when abs(diff) = 0 then '0 s'
                    when abs(diff) <= 2 then '1-2 s'
                    when abs(diff) <= 10 then '3-10 s'
                    when abs(diff) <= 60 then '11-60 s'
                    else 'over 60 s' end as difference,
               count(*) as skaters
        from cmp group by 1 order by min(abs(diff))
        """
    ).show()

    print("Shifts and games played")
    con.sql(
        """
        select sum((our_shifts = nhl_shifts)::integer) as same_shift_count,
               sum((our_shifts > nhl_shifts)::integer) as we_have_more_shifts,
               sum((our_shifts < nhl_shifts)::integer) as we_have_fewer_shifts,
               sum((our_gp = nhl_gp)::integer) as same_games_played
        from cmp
        """
    ).show()

    con.execute(
        f"""
        create temp table merged as
        with s as (
            select player_id, game_id, period,
                   start_game_seconds as st, end_game_seconds as en
            from '{shifts}' where not is_goalie
        ),
        o as (
            select *, max(en) over (
                partition by player_id, game_id, period order by st, en
                rows between unbounded preceding and 1 preceding) as previous_end
            from s
        ),
        g as (
            select *, sum(case when previous_end is null or st > previous_end then 1 else 0 end)
                over (partition by player_id, game_id, period order by st, en
                      rows between unbounded preceding and current row) as stretch
            from o
        )
        select player_id, sum(stretch_end - stretch_start) as toi
        from (
            select player_id, game_id, period, stretch,
                   min(st) as stretch_start, max(en) as stretch_end
            from g group by 1, 2, 3, 4
        )
        group by 1
        """
    )
    print("Total time on ice if overlapping shifts are merged into one stretch")
    con.sql(
        """
        select count(*) as skaters,
               sum((m.toi = r.toi)::integer) as exact,
               sum((abs(m.toi - r.toi) <= 2)::integer) as within_2_s,
               sum((m.toi > r.toi + 2)::integer) as still_higher,
               sum((m.toi < r.toi - 2)::integer) as now_lower
        from ref as r join merged as m on m.player_id = r.player_id
        """
    ).show()

    print("Are our extra shifts the flagged (conflicting) ones?")
    con.sql(
        """
        select count(*) filter (where our_shifts > nhl_shifts) as players_with_extra_shifts,
               count(*) filter (where our_shifts > nhl_shifts and flagged = 0) as extra_but_none_flagged,
               count(*) filter (where our_shifts > nhl_shifts
                                and our_shifts - nhl_shifts = flagged) as extra_equals_flagged,
               count(*) filter (where our_shifts > nhl_shifts
                                and 2 * (our_shifts - nhl_shifts) = flagged) as extra_is_half_of_flagged
        from cmp
        """
    ).show()

    print("Ten largest differences in time on ice")
    con.sql(
        """
        select player_id, name, nhl_toi, our_toi, diff, nhl_gp, our_gp
        from cmp order by abs(diff) desc limit 10
        """
    ).show()


if __name__ == "__main__":
    main()
