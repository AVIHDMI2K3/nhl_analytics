"""Tests for src/nhl_pipeline/transform/shift_reports.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import shift_reports as s  # noqa: E402

HTML = """
<td class="teamHeading + border" align="center">NEW YORK ISLANDERS</td>
<td class="playerHeading + border" colspan="8">3 PELECH, ADAM</td>
<tr><td class="heading">Shift #</td><td class="heading">Per</td></tr>
<tr class="oddColor"><td>1</td><td>1</td><td>0:00 / 20:00</td><td>0:25 / 19:35</td><td>00:25</td><td>&nbsp;</td></tr>
<tr class=" evenColor"><td>2</td><td>3</td><td>10:09 / 9:51</td><td>10:54 / 9:06</td><td>00:45</td><td>G</td></tr>
<tr class="oddColor"><td>3</td><td>OT</td><td>1:00 / 4:00</td><td>1:30 / 3:30</td><td>00:30</td><td>&nbsp;</td></tr>
<tr class="oddColor"><td>SHF</td><td>AVG</td><td>TOI</td></tr>
<td class="playerHeading + border" colspan="8">91 TAVARES, JOHN</td>
<tr class="oddColor"><td>1</td><td>2</td><td>2:00 / 18:00</td><td>3:00 / 17:00</td><td>01:00</td><td>&nbsp;</td></tr>
"""


def test_periods_start_at_the_right_game_second():
    assert [s.period_start(p) for p in (1, 2, 3, 4)] == [0, 1200, 2400, 3600]
    assert s.parse_period("OT") == 4 and s.parse_period("2") == 2 and s.parse_period("SO") is None


def test_a_report_is_parsed_into_players_and_shifts_in_game_seconds():
    parsed = s.parse_report(HTML)
    assert parsed["team"] == "NEW YORK ISLANDERS" and [p["number"] for p in parsed["players"]] == [3, 91]
    first = parsed["players"][0]["shifts"]
    assert first == [{"shift_number": 1, "period": 1, "start": 0, "end": 25},
                     {"shift_number": 2, "period": 3, "start": 2400 + 609, "end": 2400 + 654},
                     {"shift_number": 3, "period": 4, "start": 3660, "end": 3690}]
    assert parsed["players"][1]["shifts"] == [{"shift_number": 1, "period": 2, "start": 1320, "end": 1380}]


def test_players_are_matched_to_ids_by_jersey_number_and_unmatched_ones_are_reported():
    rows, unmatched = s.shift_rows(7, 2, s.parse_report(HTML), {3: 8470001})
    assert len(rows) == 3 and rows[0]["player_id"] == 8470001 and rows[0]["team_id"] == 2 and rows[0]["shift_id"] is None
    assert rows[0]["start_game_seconds"] == 0 and unmatched == [(91, "TAVARES, JOHN")]


def test_shifts_are_checked_against_the_boxscore_time_on_ice():
    rows, _ = s.shift_rows(7, 2, s.parse_report(HTML), {3: 100, 91: 200})
    # player 100 has 25 + 45 + 30 = 100 seconds in the report, player 200 has 60
    assert s.toi_differences(rows, {100: 100, 200: 60}) == []
    assert s.toi_differences(rows, {100: 103, 200: 60, 300: 40}) == [(100, 100, 103), (300, 0, 40)]
    assert s.toi_differences(rows, {100: 101, 200: 59}) == []  # within the 2-second tolerance


def test_a_shift_row_becomes_a_staging_row():
    rows, _ = s.shift_rows(7, 2, s.parse_report(HTML), {3: 100})
    row = s.to_staging_row(rows[1], "NYI", 2024)  # period 3, 10:09 to 10:54
    assert row["first_name"] == "Adam" and row["last_name"] == "Pelech" and row["team"] == "NYI" and row["shift_id"] is None
    assert (row["start_seconds_in_period"], row["end_seconds_in_period"], row["duration_seconds"]) == (609, 654, 45)
    assert (row["start_game_seconds"], row["end_game_seconds"], row["season"]) == (3009, 3054, 2024)