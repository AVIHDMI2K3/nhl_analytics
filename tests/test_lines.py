"""Tests for src/nhl_pipeline/transform/lines.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))

from lines import units_on_ice  # noqa: E402

POSITIONS = {1: "F", 2: "F", 3: "F", 4: "F", 5: "D", 6: "D", 7: "D", 8: "F"}


def test_three_forwards_and_two_defensemen_make_a_line_and_a_pair():
    line, pair = units_on_ice([1, 2, 3, 5, 6], POSITIONS)
    assert line == frozenset({1, 2, 3}) and pair == frozenset({5, 6})


def test_four_forwards_and_one_defenseman_make_neither():
    assert units_on_ice([1, 2, 3, 4, 5], POSITIONS) == (None, None)


def test_two_forwards_and_three_defensemen_make_neither():
    assert units_on_ice([1, 2, 5, 6, 7], POSITIONS) == (None, None)


def test_a_skater_without_a_known_position_makes_neither():
    assert units_on_ice([1, 2, 3, 5, 99], POSITIONS) == (None, None)


def test_the_order_of_the_skaters_does_not_matter():
    assert units_on_ice([6, 3, 5, 1, 2], POSITIONS) == units_on_ice([1, 2, 3, 5, 6], POSITIONS)


def test_a_unit_is_found_even_if_the_other_is_not():
    # 3 forwards and 1 defenseman (a skater short): the line is there, the pair is not
    assert units_on_ice([1, 2, 3, 5], POSITIONS) == (frozenset({1, 2, 3}), None)
