"""Tests for the helpers of scripts/check_html_shift_reports.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_html_shift_reports as c  # noqa: E402


def test_report_urls_follow_the_season_and_game_number():
    assert c.report_url(2024021235, "TH") == "https://www.nhl.com/scores/htmlreports/20242025/TH021235.HTM"
    assert c.report_url(2023020130, "TV") == "https://www.nhl.com/scores/htmlreports/20232024/TV020130.HTM"


def test_players_and_shift_rows_are_counted():
    html = ('<td class="playerHeading + border">8 SMITH, A</td><tr><td>1</td><td>1</td><td>0:00 / 20:00</td></tr>'
            '<td class="playerHeading">9 JONES, B</td><tr><td>2</td><td>1</td><td>1:10 / 18:50</td></tr>')
    assert c.summarize(html) == (2, 2) and c.summarize("<html></html>") == (0, 0)