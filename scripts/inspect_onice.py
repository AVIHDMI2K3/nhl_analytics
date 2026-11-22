"""Phase 3 check: look closely at where the on-ice tables disagree with the NHL.

Run from the repo root with the `nhl` conda environment active:

    python scripts/inspect_onice.py --season 2023

Read-only. It reads data/intermediate/season=YYYY/ and the staging tables and prints:

  1. Which situationCode digit disagrees, by event type.
  2. The most common (situationCode, on-ice) pairs among the disagreements.
  3. A sample of disagreeing events with the event just before them.
  4. Games with the most disagreements.
  5. Games where our plus/minus differs from the boxscore, and every goal
     in the three worst ones, so the differing goals can be found.

"On-ice" codes are written in the situationCode order:
[away goalie][away skaters][home skaters][home goalie].
"""

import argparse
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"

ON_ICE = "concat(away_goalies_on_ice, away_skaters_on_ice, home_skaters_on_ice, home_goalies_on_ice)"


def table_path(root, season, table):
    return (root / f"season={season}" / f"{table}.parquet").as_posix()


def main():
    parser = argparse.ArgumentParser(description="Inspect on-ice disagreements.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--rows", type=int, default=20, help="rows to show in the lists")
    args = parser.parse_args()

    event_on_ice = table_path(INTERMEDIATE_ROOT, args.season, "event_on_ice")
    plus_minus = table_path(INTERMEDIATE_ROOT, args.season, "player_game_plus_minus")
    games = table_path(STAGING_ROOT, args.season, "games")
    box = table_path(STAGING_ROOT, args.season, "boxscore_players")

    con = duckdb.connect()
    con.execute(f"create temp view ev as select * from '{event_on_ice}'")

    print("\n1. Which situationCode digit disagrees (count of events), by event type")
    con.sql(
        """
        select event_type,
            count(*) as disagreeing_events,
            sum((away_goalie_code <> away_goalies_on_ice)::integer) as away_goalie,
            sum((away_skaters_code <> away_skaters_on_ice)::integer) as away_skaters,
            sum((home_skaters_code <> home_skaters_on_ice)::integer) as home_skaters,
            sum((home_goalie_code <> home_goalies_on_ice)::integer) as home_goalie
        from ev
        where matches_situation = false
        group by 1
        order by 2 desc
        """
    ).show()

    print("2. Most common (situationCode, on-ice) pairs among the disagreements")
    con.sql(
        f"""
        select event_type, situation_code as code, {ON_ICE} as on_ice, count(*) as events
        from ev
        where matches_situation = false
        group by 1, 2, 3
        order by events desc
        limit {args.rows}
        """
    ).show()

    print("3. Disagreeing events, with the event just before them")
    con.sql(
        f"""
        with ordered as (
            select *,
                lag(event_type) over (partition by game_id order by sort_order, event_id)
                    as previous_event,
                lag(game_seconds) over (partition by game_id order by sort_order, event_id)
                    as previous_seconds
            from ev
        )
        select game_id, period, game_seconds, event_type, previous_event,
               game_seconds - previous_seconds as seconds_after_previous,
               situation_code as code, {ON_ICE} as on_ice,
               uses_conflicting_shift as conflict
        from ordered
        where matches_situation = false
        order by game_id, sort_order
        limit {args.rows}
        """
    ).show()

    print("4. Games with the most disagreements")
    con.sql(
        """
        select game_id, count(*) as disagreeing_events
        from ev where matches_situation = false
        group by 1 order by 2 desc, 1 limit 10
        """
    ).show()

    con.execute(
        f"""
        create temp table pm_diff as
        select b.game_id, b.player_id, coalesce(p.plus_minus, 0) - b.plus_minus as diff
        from '{box}' as b
        left join '{plus_minus}' as p
            on p.game_id = b.game_id and p.player_id = b.player_id
        where b.player_group <> 'goalies'
          and b.plus_minus is not null
          and b.game_id in (select distinct game_id from ev)
        """
    )
    print("5. Games where our plus/minus differs from the boxscore (ours minus boxscore)")
    con.sql(
        """
        select game_id,
            count(*) filter (where diff <> 0) as players_differing,
            count(*) filter (where diff > 0) as ours_higher,
            count(*) filter (where diff < 0) as ours_lower
        from pm_diff
        group by 1
        having count(*) filter (where diff <> 0) > 0
        order by players_differing desc, game_id
        limit 10
        """
    ).show()

    worst = con.execute(
        """
        select game_id from pm_diff
        group by 1
        having count(*) filter (where diff <> 0) > 0
        order by count(*) filter (where diff <> 0) desc, game_id
        limit 3
        """
    ).fetchall()
    if not worst:
        return
    game_list = ", ".join(str(row[0]) for row in worst)
    print(f"Every goal in the worst games ({game_list})")
    con.sql(
        f"""
        select e.game_id, e.period, e.game_seconds,
               case when e.event_owner_team_id = g.home_team_id then 'home' else 'away' end
                   as scored_by,
               e.situation_code as code, {ON_ICE} as on_ice,
               e.matches_situation as matches, e.uses_conflicting_shift as conflict
        from ev as e
        join '{games}' as g on g.game_id = e.game_id
        where e.event_type = 'goal' and e.game_id in ({game_list})
        order by e.game_id, e.sort_order
        """
    ).show()


if __name__ == "__main__":
    main()
