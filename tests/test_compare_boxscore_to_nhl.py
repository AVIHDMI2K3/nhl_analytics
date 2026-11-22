"""Tests for the comparison script's parsing, using made-up HTML (NOT the real NHL page layout)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import compare_boxscore_to_nhl as cmp  # noqa: E402

PAGE = """
<table><tr><td>
  <table>
    <tr><td>#</td><td>POS</td><td>NAME</td><td>G</td><td>A</td><td>+/-</td><td>TOI</td></tr>
    <tr><td>9</td><td>C</td><td>A PLAYER</td><td>1</td><td>0</td><td>+1</td><td>18:05</td></tr>
  </table>
  <table>
    <tr><td>#</td><td>POS</td><td>NAME</td><td>G</td><td>A</td><td>+/-</td><td>TOI</td></tr>
    <tr><td>4</td><td>D</td><td>B&nbsp;PLAYER</td><td>0</td><td>2</td><td>-1</td><td>20:00</td></tr>
  </table>
</td></tr></table>
"""


def test_to_number():
    assert [cmp.to_number(t) for t in ("+1", "-2", "0", "18:05", "", "x")] == [1, -2, 0, 1085, None, None]


def test_reads_both_skater_tables_by_header_name():
    players, used, problems = cmp.read_official(PAGE)
    assert not problems
    assert players[("away", 9)] == {"goals": 1, "assists": 0, "plus_minus": 1, "toi_seconds": 1085}
    assert players[("home", 4)]["plus_minus"] == -1
    assert used["away"]["+/-"] == "plus_minus"


def test_compare_counts_same_and_different_values():
    official, _, _ = cmp.read_official(PAGE)
    box = {
        ("away", 9): {"player_id": 1, "goals": 1, "assists": 0, "plus_minus": 0, "toi_seconds": 1085},
        ("home", 4): {"player_id": 2, "goals": 0, "assists": 2, "plus_minus": -1, "toi_seconds": 1200},
    }
    compared, same, differences, unmatched = cmp.compare_game(1, official, box)
    assert compared["goals"] == 2 and same["goals"] == 2
    assert [d["column"] for d in differences] == ["plus_minus"]
    assert not unmatched


REAL_STYLE = """
<table>
<tr><td>SAN JOSE SHARKS</td><td>G</td><td>A</td><td>P</td><td>+/-</td><td>PN</td><td>PIM</td><td>TOI</td><td>S</td><td>HT</td><td>GV</td><td>TK</td><td>BS</td></tr>
<tr><td>TOT</td><td>SHF</td><td>AVG</td><td>PP</td><td>SH</td><td>EV</td></tr>
<tr><td>3</td><td>D</td><td>A, B</td><td></td><td></td><td></td><td>-1</td><td>1</td><td>2</td><td>21:18</td><td>20</td><td>01:03</td><td>02:07</td><td>00:00</td><td>19:11</td><td>1</td><td>2</td><td></td><td>1</td><td>4</td></tr>
<tr><td>30</td><td>G</td><td>GOALIE</td><td></td></tr>
</table>
<table>
<tr><td>CALGARY FLAMES</td><td>G</td><td>A</td><td>P</td><td>+/-</td><td>PN</td><td>PIM</td><td>TOI</td><td>S</td><td>HT</td><td>GV</td><td>TK</td><td>BS</td></tr>
<tr><td>TOT</td><td>SHF</td><td>AVG</td><td>PP</td><td>SH</td><td>EV</td></tr>
<tr><td>20</td><td>L</td><td>C, D</td><td>1</td><td></td><td>1</td><td>+2</td><td></td><td></td><td>15:19</td><td>24</td><td>00:38</td><td>00:24</td><td>02:00</td><td>12:55</td><td>3</td><td>1</td><td>2</td><td></td><td></td></tr>
</table>
"""


def test_real_style_header_split_over_two_rows_and_blank_means_zero():
    players, _, problems = cmp.read_official(REAL_STYLE)
    assert not problems
    assert players[("away", 3)] == {
        "goals": 0,
        "assists": 0,
        "plus_minus": -1,
        "pim": 2,
        "toi_seconds": 1278,
        "sog": 1,
        "hits": 2,
        "giveaways": 0,
        "takeaways": 1,
        "blocked_shots": 4,
    }
    assert players[("home", 20)]["goals"] == 1 and players[("home", 20)]["plus_minus"] == 2
    assert ("away", 30) not in players  # goalies are skipped
