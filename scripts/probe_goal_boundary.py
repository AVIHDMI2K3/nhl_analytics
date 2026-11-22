"""Phase 3 calibration: which boundary rule for goals best matches the boxscore plus/minus?

Run from the repo root with the `nhl` conda environment active, after build_onice.py:

    python scripts/probe_goal_boundary.py --season 2023

Read-only. A goal and a shift are both timed in whole seconds, so when a shift starts
or ends on the goal's second it is unclear whether the player was on the ice. This
recomputes every skater's plus/minus under four rules for that second and counts how
many skater-games match the boxscore exactly:

    A: shift covers  start <= t <  end
    B: shift covers  start <  t <= end   (the rule build_onice.py uses now)
    C: shift covers  start <= t <= end
    D: shift covers  start <  t <  end

Power-play goals and penalty-shot goals are left out in the same way as in onice.py.
Rule B should reproduce the numbers printed by build_onice.py.
"""

import argparse
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"
INTERMEDIATE_ROOT = REPO_ROOT / "data" / "intermediate"

RULES = {
    "A: start<=t<end": "s.start_game_seconds <= g.t and g.t < s.end_game_seconds",
    "B: start<t<=end (current)": "s.start_game_seconds < g.t and g.t <= s.end_game_seconds",
    "C: start<=t<=end": "s.start_game_seconds <= g.t and g.t <= s.end_game_seconds",
    "D: start<t<end": "s.start_game_seconds < g.t and g.t < s.end_game_seconds",
}


def table_path(root, season, table):
    return (root / f"season={season}" / f"{table}.parquet").as_posix()


def main():
    parser = argparse.ArgumentParser(description="Compare goal boundary rules.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    events = table_path(INTERMEDIATE_ROOT, args.season, "event_on_ice")
    shifts = table_path(INTERMEDIATE_ROOT, args.season, "shifts_clean")
    games = table_path(STAGING_ROOT, args.season, "games")
    box = table_path(STAGING_ROOT, args.season, "boxscore_players")

    con = duckdb.connect()
    con.execute(
        f"""
        create temp table counted_goals as
        with goals as (
            select e.game_id, e.event_id, e.game_seconds as t, e.event_owner_team_id as owner,
                case when e.event_owner_team_id = g.home_team_id
                     then e.home_skaters_code else e.away_skaters_code end as own_sk,
                case when e.event_owner_team_id = g.home_team_id
                     then e.home_goalie_code else e.away_goalie_code end as own_g,
                case when e.event_owner_team_id = g.home_team_id
                     then e.away_skaters_code else e.home_skaters_code end as other_sk,
                case when e.event_owner_team_id = g.home_team_id
                     then e.away_goalie_code else e.home_goalie_code end as other_g
            from '{events}' as e
            join '{games}' as g on g.game_id = e.game_id
            where e.event_type = 'goal' and e.home_skaters_code is not null
        )
        select * from goals
        where not (own_sk = 1 and own_g = 0 and other_sk = 0 and other_g = 1)
          and not (own_sk - (case when own_g = 0 then 1 else 0 end)
                   > other_sk - (case when other_g = 0 then 1 else 0 end))
        """
    )
    con.execute(
        f"""
        create temp table skaters as
        select game_id, player_id, plus_minus as official
        from '{box}'
        where player_group <> 'goalies' and plus_minus is not null
          and game_id in (select distinct game_id from '{events}')
        """
    )

    print(f"Season {args.season}: skater-games compared against the boxscore\n")
    print(f"{'rule':28s} {'skater-games':>13} {'exact':>8} {'exact %':>8} {'ours higher':>12} {'ours lower':>11}")
    for name, condition in RULES.items():
        row = con.execute(
            f"""
            with effect as (
                select game_id, player_id, sum(sign) as ours
                from (
                    select distinct g.game_id, g.event_id, s.player_id,
                        case when s.team_id = g.owner then 1 else -1 end as sign
                    from counted_goals as g
                    join '{shifts}' as s
                        on s.game_id = g.game_id and not s.is_goalie and {condition}
                )
                group by 1, 2
            )
            select count(*),
                sum((coalesce(e.ours, 0) = k.official)::integer),
                sum((coalesce(e.ours, 0) > k.official)::integer),
                sum((coalesce(e.ours, 0) < k.official)::integer)
            from skaters as k
            left join effect as e on e.game_id = k.game_id and e.player_id = k.player_id
            """
        ).fetchone()
        total, exact, higher, lower = row
        print(f"{name:28s} {total:>13} {exact:>8} {100 * exact / total:>7.2f}% {higher:>12} {lower:>11}")


if __name__ == "__main__":
    main()
