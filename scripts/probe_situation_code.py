"""Phase 3 calibration: how does situationCode relate to who is on the ice?

Run from the repo root with the `nhl` conda environment active:

    python scripts/probe_situation_code.py --season 2023

Read-only. For every event in games that have shift data, this counts the
skaters and goalies each team has on the ice according to the shift chart,
under three rules for an event that falls exactly on the second a shift starts
or ends:

    A: shift covers  start <= t <  end
    B: shift covers  start <  t <= end
    C: shift covers  start <= t <= end

It then compares those counts with the four digits of situationCode. It prints
two tables:

  1. For each rule and each digit position, how often the digit equals each of
     the four counts (home skaters, away skaters, home goalie, away goalie).
     The matching pair shows which digit means what.
  2. Using the order [away goalie][away skaters][home skaters][home goalie],
     how often all four digits equal the shift-chart counts, by event type.
     That order is an assumption; table 1 tells us whether it is right.

Shootout events and games without shift data are left out.
"""

import argparse
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGING_ROOT = REPO_ROOT / "data" / "staging"

RULES = {
    "A: start<=t<end": "sh.st <= ev.t and ev.t < sh.en",
    "B: start<t<=end": "sh.st < ev.t and ev.t <= sh.en",
    "C: start<=t<=end": "sh.st <= ev.t and ev.t <= sh.en",
}


def table_path(season, table):
    return (STAGING_ROOT / f"season={season}" / f"{table}.parquet").as_posix()


def build_observations(con, season):
    """Create table `obs`: on-ice counts per event under each rule."""
    con.execute(
        f"""
        create temp table sh as
        select distinct
            s.game_id, s.team_id, s.player_id,
            s.start_game_seconds as st, s.end_game_seconds as en,
            (b.player_group = 'goalies') as is_goalie
        from '{table_path(season, "shifts")}' as s
        join '{table_path(season, "boxscore_players")}' as b
            on b.game_id = s.game_id and b.player_id = s.player_id
        """
    )
    con.execute(
        f"""
        create temp table ev as
        select e.game_id, e.event_id, e.event_type, e.game_seconds as t,
               e.situation_code, g.home_team_id, g.away_team_id
        from '{table_path(season, "events")}' as e
        join '{table_path(season, "games")}' as g on g.game_id = e.game_id
        where g.shift_status = 'ok'
          and e.period_type <> 'SO'
          and length(e.situation_code) = 4
        """
    )
    queries = []
    for rule, condition in RULES.items():
        queries.append(
            f"""
            select ev.game_id, ev.event_id, ev.event_type, ev.situation_code,
                   '{rule}' as rule,
                   count(*) filter (where sh.team_id = ev.home_team_id and not sh.is_goalie) as home_sk,
                   count(*) filter (where sh.team_id = ev.away_team_id and not sh.is_goalie) as away_sk,
                   count(*) filter (where sh.team_id = ev.home_team_id and sh.is_goalie) as home_g,
                   count(*) filter (where sh.team_id = ev.away_team_id and sh.is_goalie) as away_g
            from ev
            left join sh on sh.game_id = ev.game_id and {condition}
            group by 1, 2, 3, 4
            """
        )
    con.execute("create temp table obs as " + " union all ".join(queries))
    n = con.execute("select count(distinct (game_id, event_id)) from obs").fetchone()[0]
    print(f"Events compared: {n}")


def digit_matrix(con):
    print("\nTable 1: how often each situationCode digit equals each on-ice count (%)")
    parts = []
    for position in range(1, 5):
        digit = f"try_cast(substr(situation_code, {position}, 1) as integer)"
        parts.append(
            f"""
            select rule, {position} as digit_position,
                   round(100 * avg(({digit} = home_sk)::integer), 1) as home_skaters,
                   round(100 * avg(({digit} = away_sk)::integer), 1) as away_skaters,
                   round(100 * avg(({digit} = home_g)::integer), 1) as home_goalie,
                   round(100 * avg(({digit} = away_g)::integer), 1) as away_goalie
            from obs group by rule
            """
        )
    con.sql(" union all ".join(parts) + " order by rule, digit_position").show()


def agreement_by_event_type(con):
    print(
        "Table 2: % of events where all four digits match the shift-chart counts,\n"
        "order assumed: [away goalie][away skaters][home skaters][home goalie]"
    )
    match = (
        "(try_cast(substr(situation_code, 1, 1) as integer) = away_g "
        "and try_cast(substr(situation_code, 2, 1) as integer) = away_sk "
        "and try_cast(substr(situation_code, 3, 1) as integer) = home_sk "
        "and try_cast(substr(situation_code, 4, 1) as integer) = home_g)::integer"
    )
    con.sql(
        f"""
        select event_type, count(distinct (game_id, event_id)) as events,
            round(100 * avg(case when rule like 'A%' then {match} end), 1) as rule_A,
            round(100 * avg(case when rule like 'B%' then {match} end), 1) as rule_B,
            round(100 * avg(case when rule like 'C%' then {match} end), 1) as rule_C
        from obs group by event_type
        union all
        select 'ALL EVENTS', count(distinct (game_id, event_id)),
            round(100 * avg(case when rule like 'A%' then {match} end), 1),
            round(100 * avg(case when rule like 'B%' then {match} end), 1),
            round(100 * avg(case when rule like 'C%' then {match} end), 1)
        from obs
        order by events desc
        """
    ).show()


def main():
    parser = argparse.ArgumentParser(description="Calibrate situationCode against shifts.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    con = duckdb.connect()
    build_observations(con, args.season)
    digit_matrix(con)
    agreement_by_event_type(con)


if __name__ == "__main__":
    main()
