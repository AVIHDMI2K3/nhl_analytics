"""Tests for the Phase 2 staging code. They use small made-up responses, no network.

The made-up responses follow the field names seen in the real data, but they are
not copies of it. The first run on real files (stage_season.py) is the real test.
"""

import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "ingest"))

import rawstore  # noqa: E402
import stage_season  # noqa: E402
import staging  # noqa: E402

GAME = 2023021148
HOME, AWAY = 9, 13


def pbp_fixture():
    def play(event_id, period, clock, key, owner=None, **details):
        det = dict(details)
        if owner is not None:
            det["eventOwnerTeamId"] = owner
        return {
            "eventId": event_id,
            "sortOrder": event_id * 10,
            "periodDescriptor": {"number": period, "periodType": {4: "OT", 5: "SO"}.get(period, "REG")},
            "timeInPeriod": clock,
            "timeRemaining": "00:00",
            "situationCode": "1551",
            "typeCode": 506,
            "typeDescKey": key,
            "homeTeamDefendingSide": "left",
            "details": det,
        }

    return {
        "id": GAME,
        "rosterSpots": [
            {
                "teamId": HOME,
                "playerId": 1,
                "firstName": {"default": "Brady"},
                "lastName": {"default": "Tkachuk"},
                "sweaterNumber": 7,
                "positionCode": "L",
            }
        ],
        "plays": [
            play(1, 1, "00:00", "faceoff", HOME, xCoord=0, yCoord=0, zoneCode="N"),
            play(
                2,
                1,
                "11:39",
                "shot-on-goal",
                HOME,
                xCoord=60.0,
                yCoord=-5,
                shootingPlayerId=1,
                shotType="wrist",
                goalieInNetId=99,
            ),
            play(3, 2, "05:00", "goal", HOME, scoringPlayerId=1, awaySOG=4, homeSOG=6),
            play(4, 3, "19:59", "goal", AWAY, scoringPlayerId=2),
            play(5, 4, "01:00", "goal", HOME, scoringPlayerId=1),
            play(6, 5, "00:00", "goal", HOME, scoringPlayerId=1),  # shootout attempt
            play(
                7,
                1,
                "12:00",
                "penalty",
                AWAY,
                descKey="tripping",
                typeCode="MIN",
                duration=2,
                committedByPlayerId=2,
                someNewField="x",
            ),
        ],
    }


# ---- helpers ----------------------------------------------------------------


def test_clock_to_seconds_handles_good_and_bad_values():
    assert staging.clock_to_seconds("11:39") == 699
    assert staging.clock_to_seconds("00:00") == 0
    assert staging.clock_to_seconds(None) is None
    assert staging.clock_to_seconds("") is None
    assert staging.clock_to_seconds("abc") is None
    assert staging.clock_to_seconds("1:xx") is None


def test_period_start_seconds_for_regular_season_clock():
    assert [staging.period_start_seconds(p) for p in (1, 2, 3, 4, 5)] == [
        0,
        1200,
        2400,
        3600,
        3900,
    ]
    assert staging.period_start_seconds(None) is None


# ---- events -----------------------------------------------------------------


def test_events_have_game_seconds_named_columns_and_leftover_json():
    rows = staging.parse_events(GAME, pbp_fixture())
    assert len(rows) == 7
    shot = rows[1]
    assert shot["event_type"] == "shot-on-goal"
    assert shot["seconds_in_period"] == 699
    assert shot["game_seconds"] == 699
    assert shot["shooting_player_id"] == 1
    assert shot["goalie_in_net_id"] == 99
    assert shot["x_coord"] == 60.0
    assert shot["details_json"] is None
    assert rows[2]["game_seconds"] == 1200 + 300  # period 2, 05:00
    assert rows[4]["game_seconds"] == 3600 + 60  # overtime
    penalty = rows[6]
    assert penalty["penalty_desc_key"] == "tripping"
    assert penalty["penalty_minutes"] == 2
    assert json.loads(penalty["details_json"]) == {"someNewField": "x"}


def test_event_rows_have_exactly_the_schema_columns():
    row = staging.parse_events(GAME, pbp_fixture())[0]
    assert set(row) == {name for name, _ in stage_season.SCHEMAS["events"]}


def test_other_row_types_match_their_schemas():
    shift = staging.parse_shifts(GAME, {"data": [shift_item(1, 1, "00:10", "00:50")]})[0]
    assert set(shift) == {n for n, _ in stage_season.SCHEMAS["shifts"]}
    player = staging.parse_roster(GAME, pbp_fixture())[0]
    assert set(player) == {n for n, _ in stage_season.SCHEMAS["players"]}
    game = staging.parse_schedule_week(schedule_fixture())[0]
    expected = {n for n, _ in stage_season.SCHEMAS["games"]}
    extra = {"has_events", "has_boxscore", "shift_status", "goals_check", "shifts_backwards", "shifts_overlapping"}
    assert set(game) == expected - extra


# ---- roster -----------------------------------------------------------------


def test_snake_case_converts_the_nhl_field_names():
    assert staging.snake_case("playerId") == "player_id"
    assert staging.snake_case("evenStrengthShotsAgainst") == "even_strength_shots_against"
    assert staging.snake_case("sog") == "sog"
    assert staging.snake_case("toi_seconds") == "toi_seconds"


def test_roster_unwraps_names():
    row = staging.parse_roster(GAME, pbp_fixture())[0]
    assert (row["first_name"], row["last_name"], row["sweater_number"]) == ("Brady", "Tkachuk", 7)


# ---- shifts -----------------------------------------------------------------


def shift_item(shift_id, period, start, end, player=1, type_code=517):
    return {
        "id": shift_id,
        "typeCode": type_code,
        "playerId": player,
        "firstName": "A",
        "lastName": "B",
        "teamId": HOME,
        "teamAbbrev": "OTT",
        "period": period,
        "shiftNumber": shift_id,
        "startTime": start,
        "endTime": end,
        "duration": "00:40",
    }


def test_shifts_drop_goal_markers_and_convert_times():
    data = {"data": [shift_item(1, 2, "00:10", "00:50"), shift_item(2, 1, "00:00", "00:00", type_code=505)]}
    rows = staging.parse_shifts(GAME, data)
    assert len(rows) == 1
    assert rows[0]["start_game_seconds"] == 1210
    assert rows[0]["end_game_seconds"] == 1250
    assert rows[0]["duration_seconds"] == 40


def test_check_shifts_finds_backwards_and_overlapping():
    data = {
        "data": [
            shift_item(1, 1, "00:10", "00:50"),
            shift_item(2, 1, "00:40", "01:20"),  # overlaps shift 1
            shift_item(3, 1, "02:00", "01:30"),  # ends before it starts
            shift_item(4, 1, "00:10", "00:50", player=2),  # other player, fine
        ]
    }
    found = staging.check_shifts(staging.parse_shifts(GAME, data))
    assert found == {"backwards": 1, "overlaps": 1}


# ---- boxscore ---------------------------------------------------------------


def test_boxscore_players_flatten_names_and_add_toi_seconds():
    box = {
        "homeTeam": {"id": HOME},
        "awayTeam": {"id": AWAY},
        "playerByGameStats": {
            "homeTeam": {
                "forwards": [
                    {"playerId": 1, "name": {"default": "B. Tkachuk"}, "goals": 1, "powerPlayGoals": 0, "toi": "18:30"}
                ],
                "goalies": [{"playerId": 99, "name": {"default": "L. Ullmark"}, "saves": 30}],
            },
            "awayTeam": {"defense": [{"playerId": 2, "goals": 0, "toi": "20:00"}]},
        },
    }
    rows = staging.parse_boxscore_players(GAME, box)
    assert len(rows) == 3
    skater = rows[0]
    assert skater["name"] == "B. Tkachuk" and skater["toi_seconds"] == 1110
    assert skater["player_id"] == 1 and skater["power_play_goals"] == 0
    assert "playerId" not in skater
    assert (skater["team_id"], skater["home_or_away"], skater["player_group"]) == (HOME, "home", "forwards")
    assert rows[1]["player_group"] == "goalies" and "toi_seconds" not in rows[1]
    assert rows[2]["team_id"] == AWAY and rows[2]["home_or_away"] == "away"


# ---- schedule and goal check ------------------------------------------------


def schedule_fixture():
    def game(game_id, home, away):
        return {
            "id": game_id,
            "season": 20232024,
            "gameType": 2,
            "startTimeUTC": "2023-10-10T23:00:00Z",
            "gameState": "OFF",
            "gameScheduleState": "OK",
            "homeTeam": {"id": HOME, "abbrev": "OTT", "score": home},
            "awayTeam": {"id": AWAY, "abbrev": "FLA", "score": away},
            "periodDescriptor": {"number": 5},
            "gameOutcome": {"lastPeriodType": "SO"},
        }

    return {"gameWeek": [{"date": "2023-10-10", "games": [game(GAME, 4, 3)]}]}


def test_schedule_rows_and_merge_keep_latest():
    first = staging.parse_schedule_week(schedule_fixture())
    later = [dict(first[0], game_state="FINAL")]
    merged = staging.merge_games(first + later)
    assert len(merged) == 1 and merged[0]["game_state"] == "FINAL"
    assert first[0]["home_team"] == "OTT" and first[0]["last_period_type"] == "SO"


def test_check_goals_excludes_shootout_and_credits_the_shootout_winner():
    events = staging.parse_events(GAME, pbp_fixture())
    # Fixture: HOME scores in period 2 and overtime, AWAY once, plus one shootout goal.
    game = staging.parse_schedule_week(schedule_fixture())[0]
    game.update(home_score=3, away_score=1)  # HOME 2 + 1 SO win, AWAY 1
    assert staging.check_goals(game, events) is None
    game.update(home_score=2, away_score=1)
    assert "events" in staging.check_goals(game, events)


# ---- coercion and writing ---------------------------------------------------


def test_coerce_rows_fixes_types_without_changing_values():
    rows = [{"game_id": "5", "period": 2.0, "penalty_type_code": 7, "x_coord": 3, "event_id": None}]
    out = stage_season.coerce_rows("events", rows)[0]
    assert out["game_id"] == 5 and out["period"] == 2
    assert out["penalty_type_code"] == "7"
    assert out["x_coord"] == 3.0 and isinstance(out["x_coord"], float)
    assert out["event_id"] is None
    odd = stage_season.coerce_rows("events", [{"period": 2.5}])[0]
    assert odd["period"] == 2.5  # left alone so the write fails loudly


def test_stage_game_reads_raw_files_and_flags_missing_shifts(tmp_path):
    root = tmp_path / "raw"
    rawstore.write_gz_atomic(rawstore.raw_path(root, 2023, GAME, "play-by-play"), json.dumps(pbp_fixture()).encode())
    rawstore.write_gz_atomic(
        rawstore.raw_path(root, 2023, GAME, "boxscore"),
        json.dumps(
            {
                "homeTeam": {"id": HOME},
                "awayTeam": {"id": AWAY},
                "playerByGameStats": {"homeTeam": {"forwards": [{"playerId": 1}]}},
            }
        ).encode(),
    )
    schedule_row = staging.parse_schedule_week(schedule_fixture())[0]
    schedule_row.update(home_score=3, away_score=1)

    game, players, events, shifts, box = stage_season.stage_game(root, 2023, GAME, schedule_row)
    assert game["shift_status"] == "missing" and shifts == []
    assert game["has_events"] and game["has_boxscore"]
    assert game["goals_check"] is None
    assert len(players) == 1 and len(events) == 7 and len(box) == 1

    rawstore.write_empty_marker(root, 2023, GAME, "2026-10-24T00:00:00+00:00")
    game, *_ = stage_season.stage_game(root, 2023, GAME, schedule_row)
    assert game["shift_status"] == "none_from_nhl"

    rawstore.write_gz_atomic(
        rawstore.raw_path(root, 2023, GAME, "shiftcharts"),
        json.dumps({"data": [shift_item(1, 1, "00:10", "00:50")]}).encode(),
    )
    game, _, _, shifts, _ = stage_season.stage_game(root, 2023, GAME, schedule_row)
    assert game["shift_status"] == "ok" and len(shifts) == 1
    assert game["shifts_backwards"] == 0 and game["shifts_overlapping"] == 0


def test_parquet_round_trip(tmp_path):
    for table in stage_season.SCHEMAS:  # every schema must build, including games
        stage_season.arrow_schema(table)
    game = staging.parse_schedule_week(schedule_fixture())[0]
    game.update(
        has_events=True,
        has_boxscore=False,
        shift_status="ok",
        goals_check=None,
        shifts_backwards=None,
        shifts_overlapping=None,
    )
    games_writer = stage_season.TableWriter(tmp_path / "games.parquet", "games")
    games_writer.write([game])
    games_writer.close()
    assert pq.read_table(tmp_path / "games.parquet").num_rows == 1
    rows = staging.parse_events(GAME, pbp_fixture())
    writer = stage_season.TableWriter(tmp_path / "events.parquet", "events")
    writer.write(rows[:3])
    writer.write(rows[3:])
    writer.close()
    table = pq.read_table(tmp_path / "events.parquet")
    assert table.num_rows == 7
    assert table.column_names == [n for n, _ in stage_season.SCHEMAS["events"]]
    assert table.column("game_seconds").to_pylist()[1] == 699

    stage_season.write_inferred(
        tmp_path / "box.parquet",
        [{"game_id": 1, "goals": 1}, {"game_id": 1, "saves": 30}],
    )
    box = pq.read_table(tmp_path / "box.parquet")
    assert box.column_names == ["game_id", "goals", "saves"]
