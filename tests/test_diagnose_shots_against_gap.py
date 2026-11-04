"""Tests for the shots-against diagnosis. A tiny made-up game, no real data.

Home team 1 (goalie 10, skaters 11-15), away team 2 (goalie 40, skaters 21-25).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform")
)

import diagnose_shots_against_gap as diag  # noqa: E402
import stints  # noqa: E402

GAME = {"game_id": 1, "home_team_id": 1, "away_team_id": 2}


def shift(player, team, start, end, goalie=False):
    return {"game_id": 1, "player_id": player, "team_id": team, "period": 1,
            "start_game_seconds": start, "end_game_seconds": end, "is_goalie": goalie}


def stint_rows(home_goalie_off_from=None):
    """Home goalie leaves at `home_goalie_off_from` (a sixth skater comes on) until 100."""
    rows = [shift(40, 2, 0, 100, True)] + [shift(p, 2, 0, 100) for p in range(21, 26)]
    rows += [shift(p, 1, 0, 100) for p in range(11, 16)]
    if home_goalie_off_from is None:
        rows.append(shift(10, 1, 0, 100, True))
    else:
        rows.append(shift(10, 1, 0, home_goalie_off_from, True))
        rows.append(shift(16, 1, home_goalie_off_from, 100))
    return stints.stint_rows(GAME, stints.build_stints(GAME, rows))


def event(time, owner, goalie, kind="shot-on-goal", period_type="REG", code="1551"):
    return {"event_type": kind, "period_type": period_type, "game_seconds": time, "event_owner_team_id": owner,
            "goalie_in_net_id": goalie, "situation_code": code}


def box(team, player, group, **numbers):
    return {"team_id": team, "player_id": player, "player_group": group, "sog": 0, "shots_against": 0, **numbers}


def test_empty_net_shots_are_counted_from_events_and_shifts():
    events = [event(10, 2, 10), event(20, 2, 10), event(80, 2, None)]
    boxes = [box(2, 21, "forwards", sog=3), box(1, 10, "goalies", shots_against=2), box(1, 11, "forwards")]
    records, mismatches, goalies = diag.analyze_game(GAME, events, stint_rows(60), boxes)
    home = records[1]
    assert (home["events"], home["events_goalie"], home["events_empty"], home["stints_empty"]) == (3, 2, 1, 1)
    assert (home["box_skater_shots"], home["box_goalie_shots"]) == (3, 2)  # the opponent's skater shots, his goalie's shots against
    assert not mismatches
    assert goalies == [{"game_id": 1, "player_id": 10, "team_id": 1, "box": 2, "events": 2}]


def test_a_disagreement_is_reported_with_the_distance_to_the_goalie_change():
    # play-by-play names the goalie at 61, but our shifts say he left at 60
    records, mismatches, _ = diag.analyze_game(GAME, [event(61, 2, 10)], stint_rows(60), [])
    assert len(mismatches) == 1
    assert mismatches[0]["kind"] == "play-by-play has a goalie, shifts show none"
    assert mismatches[0]["distance"] == 1
    assert diag.bucket(1) == "1 s" and diag.bucket(2) == "2 s" and diag.bucket(40) == "more"


def test_shootout_and_other_events_are_ignored_and_penalty_shots_counted():
    events = [event(5, 2, 10, period_type="SO"), event(6, 2, 10, kind="missed-shot"),
              event(7, 2, 10, code="1010")]
    records, _, _ = diag.analyze_game(GAME, events, stint_rows(), [])
    assert records[1]["events"] == 1 and records[1]["penalty_shots"] == 1


def test_skater_shots_go_to_the_opposing_team():
    boxes = [box(2, 21, "forwards", sog=4), box(1, 11, "forwards", sog=2)]
    records, _, _ = diag.analyze_game(GAME, [], stint_rows(), boxes)
    assert records[1]["box_skater_shots"] == 4 and records[2]["box_skater_shots"] == 2


def test_team_records_have_every_count_even_when_it_is_zero():
    records, _, _ = diag.analyze_game(GAME, [], stint_rows(), [])
    row = diag.team_record(1, 1, True, records[1])
    assert set(diag.RECORD_KEYS) <= set(row) and row["events_empty"] == 0 and row["box_goalie_shots"] == 0