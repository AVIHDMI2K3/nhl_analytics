"""Tests for src/nhl_pipeline/transform/line_display.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))

import line_display as ld  # noqa: E402

INFO = {
    (1, 7): ("Brad Marchand", "L"), (2, 7): ("Charlie Coyle", "C"), (3, 7): ("David Pastrnak", "R"),
    (4, 7): ("Hampus Lindholm", "D"), (5, 7): ("Brandon Carlo", "D"), (6, 7): ("Mason Lohrei", "D"),
    (9, 7): ("Pat Maroon", "L"), (10, 7): ("Mitch Maroon", "L"),
}
UNIT = {"cf": 10, "ca": 5, "ff": 8, "fa": 4, "sf": 6, "sa": 3, "gf": 1, "ga": 0, "cf_pct": 66.7, "ff_pct": 66.7,
        "sf_pct": 66.7, "gf_pct": 100.0, "sh_pct": 16.7, "sv_pct": 100.0, "pdo": 116.7, "cf_per_60": 12.0,
        "ca_per_60": 6.0, "gf_per_60": 1.2, "ga_per_60": 0.0}


def season_row(unit_type, ids, seconds, games=10):
    return {"team_id": 7, "unit_type": unit_type, "player_ids": ids, "games": games, "seconds": seconds, **UNIT}


def test_a_unit_id_uses_the_team_type_and_sorted_player_ids():
    assert ld.unit_id("BOS", "line", [3, 1, 2]) == "BOS-line-1-2-3"
    assert ld.unit_id("BOS", "pair", [5, 4]) == "BOS-pair-4-5"


def test_a_line_reads_left_wing_center_right_wing_and_a_pair_alphabetically():
    team = {p: v for (p, _), v in INFO.items()}
    assert ld.reading_order([2, 3, 1], team, "line") == [1, 2, 3]
    assert ld.reading_order([6, 4, 5], team, "pair") == [5, 4, 6]  # Carlo, Lindholm, Lohrei


def test_a_line_with_one_center_puts_him_in_the_middle_and_other_lines_use_the_listed_order():
    info = {1: ("A Lefty", "L"), 2: ("B Lefty", "L"), 3: ("C Center", "C"), 4: ("D Righty", "R"), 5: ("E Center", "C")}
    assert ld.reading_order([2, 1, 3], info, "line") == [1, 3, 2]  # L-L-C: wingers by name around the center
    assert ld.reading_order([4, 3, 1], info, "line") == [1, 3, 4]
    assert ld.reading_order([4, 3, 5], info, "line") == [3, 5, 4]  # two centers: listed order, then name


def test_last_names_get_an_initial_only_when_two_players_of_the_team_share_one():
    team = {p: v for (p, _), v in INFO.items()}
    assert ld.last_name("Mitch Del Zotto") == "Del Zotto" and ld.last_name("Cher") == "Cher"
    assert ld.repeated_last_names(team) == {"Maroon"}
    assert ld.short_names([9, 2], team, {"Maroon"}) == ["P. Maroon", "Coyle"]


def test_only_units_with_enough_time_are_in_the_display_table_and_the_columns_are_filled():
    rows = ld.build_unit_display(
        [season_row("line", [1, 2, 3], 3 * 3600), season_row("line", [1, 2, 9], 600), season_row("pair", [4, 5], 4000)],
        INFO, {7: "BOS"})
    assert [r["unit_id"] for r in rows] == ["BOS-line-1-2-3", "BOS-pair-4-5"]
    line = rows[0]
    assert line["label"] == "Marchand / Coyle / Pastrnak" and line["positions"] == "L-C-R"
    assert (line["player_1_id"], line["player_2_id"], line["player_3_id"]) == (1, 2, 3)
    assert line["minutes"] == 180.0 and line["minutes_per_game"] == 18.0 and line["cf_pct"] == 66.7
    pair = rows[1]
    assert pair["label"] == "Carlo / Lindholm" and pair["player_3_id"] is None and pair["positions"] == "D-D"


def test_percentages_and_rates_are_rounded_for_display():
    unit = season_row("line", [1, 2, 3], 3600)
    unit.update(gf_pct=65.71428571428571, cf_per_60=12.3456, sv_pct=None)
    row = ld.build_unit_display([unit], INFO, {7: "BOS"})[0]
    assert row["gf_pct"] == 65.7 and row["cf_per_60"] == 12.35 and row["sv_pct"] is None


def test_the_minimum_time_can_be_changed_and_units_are_sorted_by_time_together():
    rows = ld.build_unit_display(
        [season_row("line", [1, 2, 9], 600), season_row("line", [1, 2, 3], 1800)], INFO, {7: "BOS"}, min_seconds=300)
    assert [r["minutes"] for r in rows] == [30.0, 10.0]


def test_zone_starts_are_added_when_given_and_zero_when_a_unit_has_no_faceoffs():
    zones = {(7, "line", (1, 2, 3)): {"oz": 6, "dz": 4, "nz": 3}}
    rows = ld.build_unit_display(
        [season_row("line", [3, 2, 1], 3600), season_row("pair", [4, 5], 3600)], INFO, {7: "BOS"}, zone_starts=zones)
    assert (rows[0]["oz_starts"], rows[0]["dz_starts"], rows[0]["nz_starts"], rows[0]["oz_start_pct"]) == (6, 4, 3, 60.0)
    assert (rows[1]["oz_starts"], rows[1]["oz_start_pct"]) == (0, None)