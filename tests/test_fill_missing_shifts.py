"""Tests for the helpers of scripts/fill_missing_shifts.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import fill_missing_shifts as f  # noqa: E402

HOME = """<td class="playerHeading + border" colspan="8">3 PELECH, ADAM</td>
<tr class="oddColor"><td>1</td><td>1</td><td>0:00 / 20:00</td><td>0:25 / 19:35</td><td>00:25</td><td>&nbsp;</td></tr>"""
AWAY = """<td class="playerHeading + border" colspan="8">9 BENSON, ZACH</td>
<tr class="oddColor"><td>1</td><td>1</td><td>0:10 / 19:50</td><td>1:10 / 18:50</td><td>01:00</td><td>&nbsp;</td></tr>
<td class="playerHeading + border" colspan="8">77 NOBODY, NO</td>
<tr class="oddColor"><td>1</td><td>1</td><td>0:10 / 19:50</td><td>0:20 / 19:40</td><td>00:10</td><td>&nbsp;</td></tr>"""


def box(player, number, side, toi):
    return {"player_id": player, "sweater_number": number, "home_or_away": side, "toi_seconds": toi}


def test_a_game_is_built_from_both_reports_and_checked_against_the_boxscore():
    players = [box(100, 3, "home", 25), box(200, 9, "away", 60)]
    rows, problems = f.build_game(7, players, {"home": 1, "away": 2}, {}, lambda side: HOME if side == "TH" else AWAY)
    assert [(r["player_id"], r["team_id"]) for r in rows] == [(100, 1), (200, 2)]
    assert problems == {"unmatched": [(77, "NOBODY, NO")], "toi": []}


def test_a_time_on_ice_difference_is_reported():
    players = [box(100, 3, "home", 40), box(200, 9, "away", 60), box(77, 77, "away", 10)]
    rows, problems = f.build_game(7, players, {"home": 1, "away": 2}, {}, lambda side: HOME if side == "TH" else AWAY)
    assert problems["unmatched"] == [] and problems["toi"] == [(100, 25, 40)] and len(rows) == 3