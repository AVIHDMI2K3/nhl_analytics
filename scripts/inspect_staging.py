"""Print a quick health check of one season's staging tables.

Run from the repo root with the `nhl` conda environment active:

    python scripts/inspect_staging.py --season 2023

Look for columns that are null in every row: that usually means a field name
in staging.py does not match the NHL's real field name. Some nulls are normal,
for example only hits have a hitter.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"


def table_path(season, table):
    return (STAGING_ROOT / f"season={season}" / f"{table}.parquet").as_posix()


def null_report(season, table):
    path = table_path(season, table)
    columns = [row[0] for row in duckdb.sql(f"describe select * from '{path}'").fetchall()]
    counts = ", ".join(f'count("{c}") as "{c}"' for c in columns)
    total = duckdb.sql(f"select count(*) from '{path}'").fetchone()[0]
    filled = duckdb.sql(f"select {counts} from '{path}'").fetchone()
    print(f"\n{table}: {total} rows. Null values per column:")
    print(f"  {'column':32s} {'nulls':>8} {'% null':>8}")
    for column, non_null in zip(columns, filled):
        nulls = total - non_null
        flag = "   <-- ALL NULL" if non_null == 0 else ""
        print(f"  {column:32s} {nulls:>8} {nulls / total:>8.1%}{flag}")


def nulls_by_event_type(season):
    """For each event type, how many rows lack the fields Corsi attribution needs."""
    print("\nMissing fields by event type (a null here can be normal for that type):")
    duckdb.sql(
        f"""
        select
            event_type,
            count(*) as events,
            count(*) - count(event_owner_team_id) as no_team,
            count(*) - count(shooting_player_id) as no_shooter,
            count(*) - count(blocking_player_id) as no_blocker,
            count(*) - count(goalie_in_net_id) as no_goalie,
            count(*) - count(x_coord) as no_coords,
            count(*) - count(zone_code) as no_zone
        from '{table_path(season, "events")}'
        group by 1 order by events desc
        """
    ).show()


def blocked_shot_attribution(season):
    """Is a blocked shot's event_owner_team_id the shooter's team or the blocker's?"""
    print("\nBlocked-shot team attribution:")
    duckdb.sql(
        f"""
        select
            count(*) as blocked_shots,
            count(*) filter (where e.event_owner_team_id = shooter.team_id)
                as owner_is_shooters_team,
            count(*) filter (where e.event_owner_team_id = blocker.team_id)
                as owner_is_blockers_team
        from '{table_path(season, "events")}' as e
        left join '{table_path(season, "players")}' as shooter
            on shooter.game_id = e.game_id and shooter.player_id = e.shooting_player_id
        left join '{table_path(season, "players")}' as blocker
            on blocker.game_id = e.game_id and blocker.player_id = e.blocking_player_id
        where e.event_type = 'blocked-shot'
        """
    ).show()


def blocked_shot_zones(season):
    """Zone of blocked shots, and examples where the blocker is on the shooter's team."""
    events = table_path(season, "events")
    players = table_path(season, "players")
    print("\nBlocked shots by zone (zone_code is relative to the event's team):")
    duckdb.sql(
        f"""
        select zone_code, count(*) as blocked_shots
        from '{events}' where event_type = 'blocked-shot'
        group by 1 order by blocked_shots desc
        """
    ).show()
    print("Blocked shots by reason, zone and which team the players are on:")
    duckdb.sql(
        f"""
        select e.reason, e.zone_code,
               count(*) as blocked_shots,
               count(*) filter (where shooter.team_id = e.event_owner_team_id)
                   as shooter_on_event_team,
               count(*) filter (where blocker.team_id = e.event_owner_team_id)
                   as blocker_on_event_team
        from '{events}' as e
        left join '{players}' as shooter
            on shooter.game_id = e.game_id and shooter.player_id = e.shooting_player_id
        left join '{players}' as blocker
            on blocker.game_id = e.game_id and blocker.player_id = e.blocking_player_id
        where e.event_type = 'blocked-shot'
        group by 1, 2 order by blocked_shots desc
        """
    ).show()
    print("Examples where the blocker is on the same team as the event's team:")
    duckdb.sql(
        f"""
        select e.game_id, e.event_id, e.period, e.time_in_period, e.zone_code,
               shooter.last_name as shooter, shooter.team_id as shooter_team,
               blocker.last_name as blocker, blocker.team_id as blocker_team,
               e.event_owner_team_id as event_team
        from '{events}' as e
        join '{players}' as shooter
            on shooter.game_id = e.game_id and shooter.player_id = e.shooting_player_id
        join '{players}' as blocker
            on blocker.game_id = e.game_id and blocker.player_id = e.blocking_player_id
        where e.event_type = 'blocked-shot'
          and blocker.team_id = e.event_owner_team_id
        order by e.game_id, e.event_id limit 10
        """
    ).show()


def shift_overlaps(season):
    """How big are the overlaps between one player's consecutive shifts?"""
    path = table_path(season, "shifts")
    pairs = f"""
        with ordered as (
            select
                game_id, player_id, period, shift_number,
                start_game_seconds, end_game_seconds,
                lag(end_game_seconds) over w as prev_end,
                lag(start_game_seconds) over w as prev_start
            from '{path}'
            window w as (
                partition by game_id, player_id, period
                order by start_game_seconds, end_game_seconds
            )
        )
        select *, prev_end - start_game_seconds as overlap_seconds,
               (start_game_seconds = prev_start
                and end_game_seconds = prev_end) as exact_duplicate
        from ordered
        where start_game_seconds < prev_end
    """
    print("\nShift overlaps (same player, same period):")
    duckdb.sql(
        f"""
        select
            case
                when exact_duplicate then 'exact duplicate shift'
                when overlap_seconds = 1 then '1 second'
                when overlap_seconds <= 5 then '2-5 seconds'
                when overlap_seconds <= 30 then '6-30 seconds'
                else 'more than 30 seconds'
            end as overlap_size,
            count(*) as pairs,
            count(distinct game_id) as games
        from ({pairs})
        group by 1 order by pairs desc
        """
    ).show()
    print("Ten largest overlaps:")
    duckdb.sql(
        f"""
        select game_id, player_id, period, shift_number, prev_start as earlier_start,
               prev_end as earlier_end, start_game_seconds as later_start,
               end_game_seconds as later_end, overlap_seconds
        from ({pairs})
        order by overlap_seconds desc limit 10
        """
    ).show()


def leftover_detail_fields(season):
    """Which fields ended up in details_json, by event type."""
    rows = duckdb.sql(
        f"""
        select event_type, details_json
        from '{table_path(season, "events")}'
        where details_json is not null
        """
    ).fetchall()
    found = defaultdict(Counter)
    for event_type, details_json in rows:
        for key in json.loads(details_json):
            found[event_type][key] += 1
    print("\nFields kept in details_json (no column of their own):")
    if not found:
        print("  none")
    for event_type, counter in sorted(found.items()):
        print(f"  {event_type}: {dict(counter)}")


def main():
    parser = argparse.ArgumentParser(description="Health check for staging tables.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    for table in ("events", "shifts", "players", "boxscore_players"):
        null_report(args.season, table)

    print("\nEvent types:")
    duckdb.sql(
        f"""
        select event_type, count(*) as n
        from '{table_path(args.season, "events")}'
        group by 1 order by n desc
        """
    ).show()

    nulls_by_event_type(args.season)
    blocked_shot_attribution(args.season)
    blocked_shot_zones(args.season)
    shift_overlaps(args.season)
    leftover_detail_fields(args.season)

    print("\nShift status per game:")
    duckdb.sql(
        f"""
        select shift_status, count(*) as games
        from '{table_path(args.season, "games")}'
        group by 1
        """
    ).show()


if __name__ == "__main__":
    main()