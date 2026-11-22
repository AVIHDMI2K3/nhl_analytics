"""Tests for the advanced on-ice stats. Made-up state rows, no real data.

Team 1 players 11 and 12; team 2 player 21. Two games.
"""

import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform"))

import advanced_stats  # noqa: E402
import base_tables  # noqa: E402
import build_player_advanced  # noqa: E402

STATE_5V5 = {"strength": "ev", "skaters_for": 5, "skaters_against": 5, "goalies_for": 1, "goalies_against": 1}
COUNTS = ["seconds"] + [f"{p}_{k}" for p in ("for", "against", "ind") for k in base_tables.KINDS] + ["blocks_made"]


def state_row(game=1, player=None, team=1, state=None, **numbers):
    row = dict.fromkeys(COUNTS, 0)
    row.update(numbers)
    row.update(state or STATE_5V5)
    row.update(game_id=game, team_id=team)
    if player is not None:
        row["player_id"] = player
    return row


def totals_for(player_rows, team_rows):
    return advanced_stats.build_advanced_counts(player_rows, team_rows)


def test_situations_of_a_state():
    assert advanced_stats.situations_of(state_row()) == ["all", "ev", "5v5"]
    empty_net = state_row(state={**STATE_5V5, "skaters_for": 6, "goalies_for": 0})
    assert advanced_stats.situations_of(empty_net) == ["all", "ev"]
    four = state_row(state={**STATE_5V5, "skaters_for": 4, "skaters_against": 4})
    assert advanced_stats.situations_of(four) == ["all", "ev"]
    assert advanced_stats.situations_of(state_row(state={**STATE_5V5, "strength": "pp"})) == ["all", "pp"]
    assert advanced_stats.situations_of(state_row(state={**STATE_5V5, "strength": "sh"})) == ["all", "sh"]


def test_counts_of_a_row():
    row = state_row(
        for_goal=1, for_sog=2, for_miss=3, for_block=4, against_sog=5, ind_goal=1, ind_block=2, blocks_made=3
    )
    counts = advanced_stats.counts_of(row, True)
    assert (counts["cf"], counts["ff"], counts["sf"], counts["gf"]) == (10, 6, 3, 1)
    assert (counts["ca"], counts["sa"], counts["ga"]) == (5, 5, 0)
    assert (counts["icf"], counts["iff"], counts["isf"], counts["ig"], counts["blocks_made"]) == (3, 1, 1, 1, 3)


def test_off_ice_is_the_team_in_the_games_he_played_minus_his_on_ice():
    player_rows = [state_row(player=11, seconds=600, for_sog=3, against_sog=1)]
    team_rows = [state_row(seconds=3000, for_sog=10, against_sog=6)]
    totals, games = totals_for(player_rows, team_rows)
    row = totals[(11, 1, "5v5")]
    assert (row["seconds"], row["sf"], row["sa"]) == (600, 3, 1)
    assert (row["off_seconds"], row["off_sf"], row["off_sa"]) == (2400, 7, 5)
    assert games == {(11, 1): 1}


def test_games_he_missed_are_not_in_his_off_ice_numbers():
    player_rows = [state_row(game=1, player=11, seconds=600, for_sog=3)]
    team_rows = [state_row(game=1, seconds=3000, for_sog=10), state_row(game=2, seconds=3000, for_sog=20)]
    totals, _ = totals_for(player_rows, team_rows)
    assert totals[(11, 1, "5v5")]["off_sf"] == 7  # game 2 is not counted


def test_a_player_adds_up_over_games_and_states_into_all_and_ev():
    pp_state = {**STATE_5V5, "strength": "pp", "skaters_for": 5, "skaters_against": 4}
    player_rows = [
        state_row(game=1, player=11, seconds=600, for_goal=1),
        state_row(game=2, player=11, seconds=300, for_goal=2),
        state_row(game=2, player=11, state=pp_state, seconds=100, for_goal=1),
    ]
    team_rows = [r for r in (dict(p) for p in player_rows)]
    totals, games = totals_for(player_rows, team_rows)
    assert totals[(11, 1, "5v5")]["gf"] == 3 and totals[(11, 1, "5v5")]["seconds"] == 900
    assert totals[(11, 1, "all")]["gf"] == 4 and totals[(11, 1, "all")]["seconds"] == 1000
    assert totals[(11, 1, "pp")]["gf"] == 1 and totals[(11, 1, "ev")]["gf"] == 3
    assert games[(11, 1)] == 2


def test_rates_from_sums_and_none_when_the_divisor_is_zero():
    counts = dict.fromkeys(advanced_stats.COUNT_COLUMNS, 0)
    counts.update(seconds=1800, cf=60, ca=40, off_cf=30, off_ca=70, gf=0, ga=0)
    row = advanced_stats.add_rates(counts)
    assert row["cf_pct"] == 60.0 and row["cf_pct_rel"] == 60.0 - 30.0
    assert row["cf_per_60"] == 120.0
    assert row["gf_pct"] is None and row["gf_pct_rel"] is None
    assert advanced_stats.add_rates(dict.fromkeys(advanced_stats.COUNT_COLUMNS, 0))["cf_per_60"] is None


def season(player, team, first, games=10, position="C"):
    return {
        "player_id": player,
        "team_id": team,
        "name": f"P{player}",
        "position": position,
        "games_played": games,
        "first_game_date": first,
    }


def test_a_traded_player_gets_a_combined_row_per_situation():
    player_rows = [
        state_row(game=1, player=11, team=1, seconds=600, for_sog=2),
        state_row(game=5, player=11, team=2, seconds=300, for_sog=1),
    ]
    team_rows = [dict(r) for r in player_rows]
    for r in team_rows:
        del r["player_id"]
    totals, games = totals_for(player_rows, team_rows)
    rows = advanced_stats.build_advanced_display(
        totals,
        games,
        [season(11, 2, "2025-12-01", 4), season(11, 1, "2025-10-01", 6)],
        {11: "Eleven"},
        {1: "AAA", 2: "BBB"},
    )
    five = [(r["kind"], r["team"]) for r in rows if r["situation"] == "5v5"]
    assert five == [("total", "TOT"), ("team", "AAA"), ("team", "BBB")]
    combined = next(r for r in rows if r["kind"] == "total" and r["situation"] == "5v5")
    assert combined["seconds"] == 900 and combined["sf"] == 3 and combined["games_played"] == 10
    assert combined["games_included"] == 2 and combined["name"] == "Eleven" and combined["teams"] == "AAA, BBB"


def test_a_player_with_one_team_has_no_combined_row_and_missing_situations_are_skipped():
    player_rows = [state_row(player=11, seconds=600)]
    totals, games = totals_for(player_rows, [dict(player_rows[0])])
    rows = advanced_stats.build_advanced_display(totals, games, [season(11, 1, "2025-10-01")], {}, {1: "AAA"})
    assert {r["kind"] for r in rows} == {"team"}
    assert {r["situation"] for r in rows} == {"all", "ev", "5v5"}  # no power-play or shorthanded time


def test_parquet_round_trip(tmp_path):
    player_rows = [state_row(player=11, seconds=600, for_sog=2)]
    totals, games = totals_for(player_rows, [dict(player_rows[0])])
    rows = advanced_stats.build_advanced_display(totals, games, [season(11, 1, "2025-10-01")], {}, {1: "AAA"})
    for row in rows:
        row["season"] = 2025
    build_player_advanced.write_table(tmp_path / "t.parquet", rows)
    table = pq.read_table(tmp_path / "t.parquet")
    assert table.column_names == build_player_advanced.SCHEMA.names and table.num_rows == len(rows)


def test_team_totals_rates_and_display():
    team_rows = [
        state_row(game=1, team=1, seconds=3000, for_goal=1, for_sog=9, against_sog=5),
        state_row(game=2, team=1, seconds=600, for_miss=4, against_block=2),
        state_row(game=1, team=2, seconds=3000, against_goal=1, against_sog=9, for_sog=5),
    ]
    totals, games = advanced_stats.build_team_advanced_counts(team_rows)
    rows = advanced_stats.build_team_advanced_display(totals, games, {1: 3, 2: 2}, {1: "AAA", 2: "BBB"})
    first = next(r for r in rows if r["team_id"] == 1 and r["situation"] == "5v5")
    assert (first["games_played"], first["games_included"], first["seconds"]) == (3, 2, 3600)
    assert (first["cf"], first["ca"], first["ff"], first["sf"], first["gf"]) == (14, 7, 14, 10, 1)
    assert first["cf_pct"] == 100 * 14 / 21 and first["cf_per_60"] == 14.0
    assert {r["situation"] for r in rows} == {"all", "ev", "5v5"} and {r["team"] for r in rows} == {"AAA", "BBB"}
    assert first["gf_pct"] == 100.0
