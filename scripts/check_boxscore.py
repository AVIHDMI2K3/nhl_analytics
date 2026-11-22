"""Compare per-player counts built from our events and shifts with the official boxscore.

Run from the repo root with the `nhl` conda environment active:

    python scripts/check_boxscore.py --season 2023

The boxscore is the NHL's own per-player, per-game result. If our counts from
play-by-play disagree with it, our parsing (or our understanding of a field)
is wrong, so this is the answer key for the staging tables.

Shootout attempts are left out of every count, as the NHL leaves them out of
player stats. Shift checks only use games that have shift data and only skaters
(the boxscore time on ice is reported for skaters and goalies differently).
"""

import argparse
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"

# Boxscore column -> (event type, event column holding the player)
# Goals and assists come from goal events, shots on goal also include goals.
EVENT_STATS = {
    "goals": [("goal", "scoring_player_id")],
    "assists": [("goal", "assist1_player_id"), ("goal", "assist2_player_id")],
    "sog": [("shot-on-goal", "shooting_player_id"), ("goal", "scoring_player_id")],
    "hits": [("hit", "hitting_player_id")],
    "blocked_shots": [("blocked-shot", "blocking_player_id")],
    "giveaways": [("giveaway", "player_id")],
    "takeaways": [("takeaway", "player_id")],
}


def table_path(season, table):
    return (STAGING_ROOT / f"season={season}" / f"{table}.parquet").as_posix()


def event_counts_sql(events):
    parts = []
    for stat, sources in EVENT_STATS.items():
        for event_type, column in sources:
            parts.append(
                f"""
                select game_id, {column} as player_id, '{stat}' as stat, count(*) as n
                from '{events}'
                where event_type = '{event_type}'
                  and period_type <> 'SO'
                  and {column} is not null
                group by 1, 2
                """
            )
    return "select game_id, player_id, stat, sum(n) as n from (" + " union all ".join(parts) + ") group by 1, 2, 3"


def boxscore_counts_sql(boxscore):
    parts = [
        f"select game_id, player_id, '{stat}' as stat, {stat} as n from '{boxscore}' where {stat} is not null"
        for stat in EVENT_STATS
    ]
    return " union all ".join(parts)


def compare_event_counts(season):
    events = table_path(season, "events")
    boxscore = table_path(season, "boxscore_players")
    print("\nEvent counts vs boxscore (one row per player per game, skaters):")
    duckdb.sql(
        f"""
        with ours as ({event_counts_sql(events)}),
             theirs as ({boxscore_counts_sql(boxscore)})
        select
            t.stat,
            count(*) as player_games,
            count(*) filter (where coalesce(o.n, 0) <> t.n) as mismatched,
            round(100.0 * count(*) filter (where coalesce(o.n, 0) <> t.n) / count(*), 2)
                as pct_mismatched,
            sum(coalesce(o.n, 0)) as our_total,
            sum(t.n) as boxscore_total
        from theirs as t
        left join ours as o using (game_id, player_id, stat)
        group by t.stat order by t.stat
        """
    ).show()


def compare_shifts(season):
    shifts = table_path(season, "shifts")
    boxscore = table_path(season, "boxscore_players")
    games = table_path(season, "games")
    print("Shifts vs boxscore (skaters, games that have shift data):")
    duckdb.sql(
        f"""
        with raw as (
            select game_id, player_id, count(*) as shifts_raw
            from '{shifts}' group by 1, 2
        ),
        unique_shifts as (
            select distinct game_id, player_id, period,
                   start_game_seconds as s, end_game_seconds as e
            from '{shifts}'
        ),
        dedup as (
            select game_id, player_id, count(*) as shifts_dedup, sum(e - s) as toi_dedup
            from unique_shifts group by 1, 2
        ),
        skaters as (
            select game_id, player_id, shifts, toi_seconds
            from '{boxscore}'
            where shifts is not null and toi_seconds is not null
              and game_id in (select game_id from '{games}' where shift_status = 'ok')
        )
        select
            count(*) as player_games,
            count(*) filter (where coalesce(r.shifts_raw, 0) <> k.shifts)
                as shift_count_off_raw,
            count(*) filter (where coalesce(d.shifts_dedup, 0) <> k.shifts)
                as shift_count_off_deduped,
            count(*) filter (where abs(coalesce(d.toi_dedup, 0) - k.toi_seconds) <= 2)
                as toi_within_2s,
            count(*) filter (where abs(coalesce(d.toi_dedup, 0) - k.toi_seconds) <= 10)
                as toi_within_10s,
            round(avg(abs(coalesce(d.toi_dedup, 0) - k.toi_seconds)), 1)
                as avg_toi_diff_seconds
        from skaters as k
        left join raw as r using (game_id, player_id)
        left join dedup as d using (game_id, player_id)
        """
    ).show()


def main():
    parser = argparse.ArgumentParser(description="Compare our per-player counts with the official boxscore.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    compare_event_counts(args.season)
    compare_shifts(args.season)


if __name__ == "__main__":
    main()
