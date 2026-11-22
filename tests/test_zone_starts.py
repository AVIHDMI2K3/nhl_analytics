"""Tests for zone_starts.py. A made-up game: home team 1, away team 2 (see test_line_tables)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))

import zone_starts as zs  # noqa: E402

GAME = {"game_id": 1, "home_team_id": 1, "away_team_id": 2}
POSITIONS = {1: "F", 2: "F", 3: "F", 4: "D", 5: "D", 6: "F", 7: "D", 11: "F", 12: "F", 13: "F", 14: "D", 15: "D"}


def stint(start, end, home=(1, 2, 3, 4, 5), away=(11, 12, 13, 14, 15), home_strength="ev", away_strength="ev"):
    return {
        "start_game_seconds": start,
        "end_game_seconds": end,
        "seconds": end - start,
        "home_skater_ids": list(home),
        "away_skater_ids": list(away),
        "home_goalie_ids": [30],
        "away_goalie_ids": [40],
        "home_strength": home_strength,
        "away_strength": away_strength,
    }


def faceoff(time, zone, owner=1, code="1551"):
    return {
        "event_type": "faceoff",
        "game_seconds": time,
        "zone_code": zone,
        "event_owner_team_id": owner,
        "situation_code": code,
    }


def counts(totals, team_id, unit_type, ids):
    return dict(totals[(team_id, unit_type, tuple(ids))])


def test_the_zone_is_in_each_teams_own_terms_and_the_stint_starting_at_the_faceoff_is_used():
    stints = [stint(0, 60), stint(60, 120, home=(6, 2, 3, 4, 5))]  # forward 6 replaces 1 at second 60
    totals, sides = zs.unit_zone_starts(GAME, stints, [faceoff(60, "O", owner=1)], POSITIONS)
    assert sides == 2
    assert counts(totals, 1, "line", (2, 3, 6)) == {"oz": 1}  # the new line is on for the faceoff
    assert counts(totals, 2, "line", (11, 12, 13)) == {"dz": 1}  # the other team sees the zone flipped
    assert (1, "line", (1, 2, 3)) not in totals
    assert counts(totals, 1, "pair", (4, 5)) == {"oz": 1} and counts(totals, 2, "pair", (14, 15)) == {"dz": 1}


def test_a_neutral_zone_faceoff_is_neutral_for_both_and_won_by_the_away_team_flips_the_owner():
    totals, _ = zs.unit_zone_starts(GAME, [stint(0, 60)], [faceoff(10, "N"), faceoff(20, "D", owner=2)], POSITIONS)
    assert counts(totals, 1, "line", (1, 2, 3)) == {"nz": 1, "oz": 1}  # the away team's dz is the home team's oz
    assert counts(totals, 2, "line", (11, 12, 13)) == {"nz": 1, "dz": 1}


def test_only_five_on_five_faceoffs_with_a_zone_inside_a_stint_count():
    stints = [stint(0, 60), stint(60, 120, away=(11, 12, 13, 14), away_strength="pp")]
    events = [
        faceoff(10, "O", code="1451"),
        faceoff(30, "O", code="1551"),
        faceoff(70, "O", code=None),
        faceoff(200, "O"),
        faceoff(20, None),
        {"event_type": "shot-on-goal", "game_seconds": 10},
    ]
    totals, sides = zs.unit_zone_starts(GAME, stints, events, POSITIONS)
    assert sides == 2 and counts(totals, 1, "line", (1, 2, 3)) == {"oz": 1}


def test_season_rows_add_the_games_and_leave_neutral_out_of_the_start_percentage():
    one, two = {(1, "line", (1, 2, 3)): {"oz": 3, "dz": 1, "nz": 2}}, {(1, "line", (1, 2, 3)): {"oz": 1, "dz": 3}}
    rows = zs.season_zone_rows([one, two])
    assert rows == [
        {"team_id": 1, "unit_type": "line", "player_ids": [1, 2, 3], "oz": 4, "dz": 4, "nz": 2, "oz_start_pct": 50.0}
    ]
    assert zs.oz_start_pct(0, 0) is None
