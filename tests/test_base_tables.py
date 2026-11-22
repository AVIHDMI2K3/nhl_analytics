"""Tests for the Phase 4.3 base-table logic. A tiny made-up game, no real data.

Teams: home = 1 (goalie 10, skaters 11-15), away = 2 (goalie 40, skaters 21-25).
"""

import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform"))

import base_tables  # noqa: E402
import build_base_tables  # noqa: E402
import stints  # noqa: E402

GAME = {"game_id": 1, "home_team_id": 1, "away_team_id": 2}


def shift(player, team, start, end, goalie=False):
    return {
        "game_id": 1,
        "player_id": player,
        "team_id": team,
        "period": 1,
        "start_game_seconds": start,
        "end_game_seconds": end,
        "is_goalie": goalie,
    }


def ice(start, end, home=range(11, 16), away=range(21, 26)):
    rows = [shift(10, 1, start, end, True), shift(40, 2, start, end, True)]
    rows += [shift(p, 1, start, end) for p in home]
    rows += [shift(p, 2, start, end) for p in away]
    return rows


def attempt(kind, time, home=True, shooter=11, blocker=None, teammate_block=None):
    return {
        "attempt_type": kind,
        "game_seconds": time,
        "is_home": home,
        "shooter_id": shooter,
        "blocker_id": blocker,
        "blocker_is_teammate": teammate_block,
    }


def tables(shift_rows, attempts):
    return base_tables.build_game_tables(GAME, stints.stint_rows(GAME, stints.build_stints(GAME, shift_rows)), attempts)


def find(rows, **wanted):
    found = [r for r in rows if all(r[k] == v for k, v in wanted.items())]
    assert len(found) == 1, found
    return found[0]


def test_seconds_per_player_and_team_and_state():
    players, teams, _ = tables(ice(0, 60) + ice(60, 100, home=range(11, 15)), [])
    assert find(players, player_id=11, strength="ev")["seconds"] == 60
    assert find(players, player_id=11, strength="sh")["seconds"] == 40
    assert find(players, player_id=15, strength="ev")["seconds"] == 60  # off the ice 60-100
    assert find(teams, team_id=1, strength="ev")["seconds"] == 60
    row = find(teams, team_id=2, strength="pp")
    assert (row["skaters_for"], row["skaters_against"], row["goalies_for"], row["goalies_against"]) == (5, 4, 1, 1)
    assert row["seconds"] == 40


def test_a_shot_credits_the_shooter_both_teams_and_the_players_on_the_ice():
    players, teams, notes = tables(ice(0, 60), [attempt("shot-on-goal", 30)])
    assert find(players, player_id=11, strength="ev")["ind_sog"] == 1
    assert find(players, player_id=12, strength="ev")["ind_sog"] == 0
    assert find(players, player_id=12, strength="ev")["for_sog"] == 1
    assert find(players, player_id=21, strength="ev")["against_sog"] == 1
    assert find(teams, team_id=1)["for_sog"] == 1 and find(teams, team_id=2)["against_sog"] == 1
    assert not notes


def test_each_attempt_kind_has_its_own_column():
    attempts = [
        attempt("goal", 10),
        attempt("shot-on-goal", 20),
        attempt("missed-shot", 30),
        attempt("blocked-shot", 40),
    ]
    players, _, _ = tables(ice(0, 60), attempts)
    row = find(players, player_id=11)
    assert [row[f"ind_{k}"] for k in base_tables.KINDS] == [1, 1, 1, 1]
    assert [row[f"for_{k}"] for k in base_tables.KINDS] == [1, 1, 1, 1]


def test_goals_are_end_inclusive_and_other_attempts_start_inclusive():
    rows = ice(0, 60) + ice(60, 120, home=range(16, 21), away=range(26, 31))
    players, _, _ = tables(rows, [attempt("goal", 60, shooter=11), attempt("shot-on-goal", 60, shooter=16)])
    assert find(players, player_id=11)["ind_goal"] == 1  # the goal belongs to the stint ending at 60
    assert find(players, player_id=16)["ind_sog"] == 1  # the shot belongs to the stint starting at 60


def test_boundary_rule_by_attempt_type_at_a_line_change():
    # all ten skaters change at 60; each attempt happens at second 60
    rows = ice(0, 60) + ice(60, 120, home=range(16, 21), away=range(26, 31))
    attempts = [
        attempt("shot-on-goal", 60, shooter=11),
        attempt("missed-shot", 60, shooter=16),
        attempt("goal", 60, shooter=11),
    ]
    players, _, _ = tables(rows, attempts)
    # shot on goal and goal: both sides from the stint ending at 60
    assert (
        find(players, player_id=11, strength="ev")["for_sog"] == 1
        and find(players, player_id=16, strength="ev")["for_sog"] == 0
    )
    assert (
        find(players, player_id=21, strength="ev")["against_sog"] == 1
        and find(players, player_id=26, strength="ev")["against_sog"] == 0
    )
    assert (
        find(players, player_id=11, strength="ev")["for_goal"] == 1
        and find(players, player_id=21, strength="ev")["against_goal"] == 1
    )
    # missed shot: the shooting side from the stint starting at 60, the defenders from the one ending at 60
    assert (
        find(players, player_id=16, strength="ev")["for_miss"] == 1
        and find(players, player_id=11, strength="ev")["for_miss"] == 0
    )
    assert (
        find(players, player_id=21, strength="ev")["against_miss"] == 1
        and find(players, player_id=26, strength="ev")["against_miss"] == 0
    )


def test_power_play_attempt_uses_each_sides_own_state():
    players, teams, _ = tables(ice(0, 60, home=range(11, 15)), [attempt("shot-on-goal", 30, home=False, shooter=21)])
    assert find(teams, team_id=2, strength="pp")["for_sog"] == 1
    assert find(teams, team_id=1, strength="sh")["against_sog"] == 1
    assert find(players, player_id=11, strength="sh")["against_sog"] == 1


def coded(kind, time, sf, sa, gf=1, ga=1, **kw):
    return {
        **attempt(kind, time, **kw),
        "skaters_for": sf,
        "skaters_against": sa,
        "goalie_for": gf,
        "goalie_against": ga,
    }


def test_state_comes_from_the_situation_code_and_players_from_the_stint():
    # the shifts say 5v5, the code says the home team is on a 5v4 power play
    players, teams, notes = tables(ice(0, 60), [coded("goal", 30, 5, 4)])
    row = find(players, player_id=12, strength="pp")
    assert row["for_goal"] == 1 and row["seconds"] == 0  # counted under the code's state, no time there
    assert find(players, player_id=12, strength="ev")["seconds"] == 60
    assert find(players, player_id=21, strength="sh")["against_goal"] == 1
    assert find(players, player_id=11, strength="pp")["ind_goal"] == 1
    assert find(teams, team_id=1, strength="pp")["for_goal"] == 1
    assert find(teams, team_id=2, strength="sh")["against_goal"] == 1
    assert notes["state_from_code"] == 1 and notes["state_differs_from_stint"] == 1


def test_a_matching_code_changes_nothing_and_is_not_counted_as_different():
    players, _, notes = tables(ice(0, 60), [coded("shot-on-goal", 30, 5, 5)])
    assert find(players, player_id=12, strength="ev")["for_sog"] == 1
    assert notes["state_from_code"] == 1 and notes["state_differs_from_stint"] == 0


def test_a_pulled_goalie_in_the_code_is_even_strength_with_six_skaters():
    _, teams, _ = tables(ice(0, 60), [coded("shot-on-goal", 30, 6, 5, gf=0)])
    row = find(teams, team_id=1, for_sog=1)
    assert (row["strength"], row["skaters_for"], row["goalies_for"]) == ("ev", 6, 0)


def test_strength_from_counts():
    assert base_tables.strength_from_counts(5, 1, 4, 1) == "pp"
    assert base_tables.strength_from_counts(4, 1, 5, 1) == "sh"
    assert base_tables.strength_from_counts(6, 0, 5, 1) == "ev"
    assert base_tables.strength_from_counts(5, 1, 6, 0) == "ev"  # the other team has pulled its goalie


def test_blocks_made_only_when_the_blocker_is_on_the_other_team():
    attempts = [
        attempt("blocked-shot", 10, blocker=21, teammate_block=False),
        attempt("blocked-shot", 20, blocker=12, teammate_block=True),
        attempt("blocked-shot", 30, blocker=22, teammate_block=None),
    ]
    players, _, _ = tables(ice(0, 60), attempts)
    assert find(players, player_id=21)["blocks_made"] == 1
    assert find(players, player_id=12)["blocks_made"] == 0
    assert find(players, player_id=22)["blocks_made"] == 0
    assert find(players, player_id=11)["ind_block"] == 3  # all three are the shooter's attempts


def test_attempts_outside_stints_and_shooters_off_the_ice_are_noted():
    players, teams, notes = tables(ice(0, 60), [attempt("shot-on-goal", 500), attempt("shot-on-goal", 30, shooter=99)])
    assert notes["attempts_outside_stints"] == 1
    assert notes["shooter_not_on_ice"] == 1
    assert find(players, player_id=99)["ind_sog"] == 1
    assert find(teams, team_id=1)["for_sog"] == 1  # only the attempt inside a stint counts


def test_a_goalie_as_shooter_counts_for_the_team_but_gets_no_skater_row():
    players, teams, notes = tables(ice(0, 60), [attempt("shot-on-goal", 30, shooter=10)])
    assert notes["goalie_shooter"] == 1 and notes["shooter_not_on_ice"] == 0
    assert all(r["player_id"] != 10 for r in players)
    assert find(players, player_id=11)["for_sog"] == 1  # the skaters on the ice still get the attempt
    assert find(teams, team_id=1)["for_sog"] == 1


def test_cases_are_recorded_when_a_list_is_given():
    records = []
    stint_rows = stints.stint_rows(GAME, stints.build_stints(GAME, ice(0, 60)))
    base_tables.build_game_tables(
        GAME,
        stint_rows,
        [attempt("shot-on-goal", 30, shooter=10), attempt("shot-on-goal", 40, shooter=99)],
        records=records,
    )
    assert [(r["kind"], r["player_id"], r["game_seconds"]) for r in records] == [
        ("goalie_shooter", 10, 30),
        ("shooter_not_on_ice", 99, 40),
    ]


def test_empty_net_is_its_own_state():
    rows = [r for r in ice(0, 60) if r["player_id"] != 40] + [shift(26, 2, 0, 60)]
    _, teams, _ = tables(rows, [])
    row = find(teams, team_id=2)
    assert (row["strength"], row["skaters_for"], row["goalies_for"]) == ("ev", 6, 0)


def test_plus_minus_by_strength():
    base = {"for_goal": 2, "against_goal": 1}
    assert base_tables.plus_minus({**base, "strength": "ev"}) == 1
    assert base_tables.plus_minus({**base, "strength": "pp"}) == -1  # power-play goals scored count for nobody
    assert base_tables.plus_minus({**base, "strength": "sh"}) == 2  # power-play goals allowed count for nobody


def test_parquet_round_trip_of_both_tables(tmp_path):
    players, teams, _ = tables(ice(0, 60), [attempt("goal", 30)])
    for row in players + teams:
        row["season"] = 2025
    build_base_tables.write_table(tmp_path / "player.parquet", players, "player_game_strength")
    build_base_tables.write_table(tmp_path / "team.parquet", teams, "team_game_strength")
    player_table = pq.read_table(tmp_path / "player.parquet")
    team_table = pq.read_table(tmp_path / "team.parquet")
    assert player_table.column_names == build_base_tables.SCHEMAS["player_game_strength"].names
    assert team_table.column_names == build_base_tables.SCHEMAS["team_game_strength"].names
    assert player_table.num_rows == len(players) and team_table.num_rows == len(teams)
    assert sum(player_table.column("ind_goal").to_pylist()) == 1
