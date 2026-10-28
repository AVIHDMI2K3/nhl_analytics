"""Tests for the Phase 1 ingestion code. They use fake responses, no network.

Run from the repo root with the `nhl` environment active:

    pytest
"""

import json
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "ingest")
)

import endpoints  # noqa: E402
import ingest_season  # noqa: E402
import rawstore  # noqa: E402

GAME = 2023021148


class FakeResponse:
    def __init__(self, payload=None, status=200, raw=None):
        self.status_code = status
        self.content = raw if raw is not None else json.dumps(payload).encode()


class FakeFetcher:
    """Answers from a dict keyed by (url, params) and records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None):
        key = (url, tuple(sorted((params or {}).items())))
        self.calls.append(key)
        return self.routes[key]


def shifts_key(game_id):
    return (
        f"{endpoints.STATS_BASE}/shiftcharts",
        (("cayenneExp", f"gameId={game_id}"),),
    )


def good_routes(game_id):
    web = endpoints.WEB_BASE
    return {
        (f"{web}/gamecenter/{game_id}/play-by-play", ()): FakeResponse(
            {"plays": [{"typeDescKey": "goal"}]}
        ),
        (f"{web}/gamecenter/{game_id}/boxscore", ()): FakeResponse(
            {"playerByGameStats": {}}
        ),
        shifts_key(game_id): FakeResponse({"data": [{"id": 1}], "total": 1}),
    }


def read_log(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---- rawstore ---------------------------------------------------------------


def test_gzip_round_trip_keeps_exact_bytes_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "a" / "x.json.gz"
    content = b'{"b": 1,  "a": [1, 2]}'
    rawstore.write_gz_atomic(path, content)
    assert rawstore.read_gz_bytes(path) == content
    assert list(path.parent.iterdir()) == [path]


def test_game_is_complete_only_when_all_three_files_exist(tmp_path):
    for name in ("play-by-play", "boxscore"):
        rawstore.write_gz_atomic(rawstore.raw_path(tmp_path, 2023, GAME, name), b"{}")
    assert not rawstore.game_is_complete(tmp_path, 2023, GAME)
    rawstore.write_gz_atomic(rawstore.raw_path(tmp_path, 2023, GAME, "shiftcharts"), b"{}")
    assert rawstore.game_is_complete(tmp_path, 2023, GAME)


# ---- ingest_game ------------------------------------------------------------


def test_ingest_game_saves_three_files_then_skips_them(tmp_path):
    log = tmp_path / "log.jsonl"
    fetcher = FakeFetcher(good_routes(GAME))

    assert ingest_season.ingest_game(fetcher, tmp_path, 2023, GAME, log) is True
    assert len(fetcher.calls) == 3
    assert rawstore.game_is_complete(tmp_path, 2023, GAME)

    assert ingest_season.ingest_game(fetcher, tmp_path, 2023, GAME, log) is True
    assert len(fetcher.calls) == 3  # nothing was fetched again

    stored = rawstore.read_gz_json(rawstore.raw_path(tmp_path, 2023, GAME, "boxscore"))
    assert stored == {"playerByGameStats": {}}
    assert [r["status"] for r in read_log(log)] == ["saved"] * 3


def test_empty_shift_chart_is_marked_not_saved_and_not_retried(tmp_path):
    log = tmp_path / "log.jsonl"
    routes = good_routes(GAME)
    routes[shifts_key(GAME)] = FakeResponse({"data": [], "total": 0})
    fetcher = FakeFetcher(routes)

    assert ingest_season.ingest_game(fetcher, tmp_path, 2023, GAME, log) is True
    assert not rawstore.raw_path(tmp_path, 2023, GAME, "shiftcharts").exists()
    assert rawstore.has_empty_marker(tmp_path, 2023, GAME)
    assert rawstore.game_is_complete(tmp_path, 2023, GAME)
    shift_events = [r for r in read_log(log) if r["endpoint"] == "shiftcharts"]
    assert [r["status"] for r in shift_events] == ["empty"]

    # A normal rerun does not ask again.
    fetcher.calls.clear()
    assert ingest_season.ingest_game(fetcher, tmp_path, 2023, GAME, log) is True
    assert fetcher.calls == []


def test_recheck_empty_saves_late_data_and_removes_the_marker(tmp_path):
    log = tmp_path / "log.jsonl"
    routes = good_routes(GAME)
    good_shifts = routes[shifts_key(GAME)]
    routes[shifts_key(GAME)] = FakeResponse({"data": [], "total": 0})
    fetcher = FakeFetcher(routes)
    ingest_season.ingest_game(fetcher, tmp_path, 2023, GAME, log)

    routes[shifts_key(GAME)] = good_shifts  # the NHL fills it in later
    fetcher.calls.clear()
    ok = ingest_season.ingest_game(fetcher, tmp_path, 2023, GAME, log, recheck_empty=True)
    assert ok is True
    assert fetcher.calls == [shifts_key(GAME)]
    assert rawstore.raw_path(tmp_path, 2023, GAME, "shiftcharts").exists()
    assert not rawstore.has_empty_marker(tmp_path, 2023, GAME)


def test_non_json_shift_response_is_invalid_and_retried(tmp_path):
    log = tmp_path / "log.jsonl"
    routes = good_routes(GAME)
    routes[shifts_key(GAME)] = FakeResponse(raw=b"<html>oops</html>")
    fetcher = FakeFetcher(routes)

    assert ingest_season.ingest_game(fetcher, tmp_path, 2023, GAME, log) is False
    assert not rawstore.has_empty_marker(tmp_path, 2023, GAME)
    assert not rawstore.game_is_complete(tmp_path, 2023, GAME)

    routes[shifts_key(GAME)] = good_routes(GAME)[shifts_key(GAME)]
    fetcher.calls.clear()
    assert ingest_season.ingest_game(fetcher, tmp_path, 2023, GAME, log) is True
    assert fetcher.calls == [shifts_key(GAME)]


def test_http_error_is_logged_and_the_game_stays_incomplete(tmp_path):
    log = tmp_path / "log.jsonl"
    routes = good_routes(GAME)
    box_key = (f"{endpoints.WEB_BASE}/gamecenter/{GAME}/boxscore", ())
    routes[box_key] = FakeResponse(status=404, raw=b"{}")

    assert (
        ingest_season.ingest_game(FakeFetcher(routes), tmp_path, 2023, GAME, log) is False
    )
    box_events = [r for r in read_log(log) if r["endpoint"] == "boxscore"]
    assert [r["status"] for r in box_events] == ["http_404"]
    assert not rawstore.game_is_complete(tmp_path, 2023, GAME)


# ---- schedule ---------------------------------------------------------------


def day(date, *games):
    return {"date": date, "games": list(games)}


def sched_game(game_id, state="OFF", schedule_state="OK"):
    return {"id": game_id, "gameState": state, "gameScheduleState": schedule_state}


def test_schedule_walk_follows_next_start_date_and_stops_after_end():
    routes = {
        (endpoints.schedule_url("2023-10-01"), ()): FakeResponse(
            {
                "nextStartDate": "2023-10-08",
                "gameWeek": [day("2023-10-03", sched_game(2023020001))],
            }
        ),
        (endpoints.schedule_url("2023-10-08"), ()): FakeResponse(
            {
                "nextStartDate": "2023-10-15",
                "gameWeek": [day("2023-10-10", sched_game(2023020002, "FUT"))],
            }
        ),
    }
    fetcher = FakeFetcher(routes)
    seen = []
    games = ingest_season.list_season_games(
        fetcher, "2023-10-01", "2023-10-14", on_week=lambda d, c: seen.append(d)
    )
    assert sorted(games) == [2023020001, 2023020002]
    assert games[2023020002]["state"] == "FUT"
    assert len(fetcher.calls) == 2
    assert seen == ["2023-10-01", "2023-10-08"]


def test_schedule_walk_raises_on_http_error():
    fetcher = FakeFetcher(
        {(endpoints.schedule_url("2023-10-01"), ()): FakeResponse(status=500, raw=b"")}
    )
    try:
        ingest_season.list_season_games(fetcher, "2023-10-01", "2023-10-14")
    except RuntimeError as exc:
        assert "500" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_select_games_keeps_finished_regular_season_games_only():
    ok = {"state": "OFF", "schedule_state": "OK"}
    games = {
        2023010001: ok,  # preseason
        2023020001: ok,
        2023020002: {"state": "FUT", "schedule_state": "OK"},
        2023020003: {"state": "OFF", "schedule_state": "PPD"},
        2023030111: ok,  # playoffs
        2024020001: ok,  # next season
    }
    assert ingest_season.select_games(games, 2023) == [2023020001]
    assert ingest_season.select_games(games, 2023, states=("FUT",)) == [2023020002]


# ---- fetcher ----------------------------------------------------------------


class FakeSession:
    headers = {}

    def __init__(self, response):
        self.response = response

    def get(self, url, params=None, timeout=None):
        return self.response


def test_fetcher_waits_between_calls():
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    fetcher = endpoints.Fetcher(
        min_interval=1.0,
        session=FakeSession(FakeResponse({})),
        clock=lambda: now[0],
        sleep=sleep,
    )
    fetcher.get("u1")  # first call never waits
    fetcher.get("u2")  # immediately after: waits the full second
    now[0] += 0.4  # the next request was slow to come back
    fetcher.get("u3")  # only the remaining 0.6 s
    assert len(sleeps) == 2
    assert abs(sleeps[0] - 1.0) < 1e-9
    assert abs(sleeps[1] - 0.6) < 1e-9


def test_fetcher_returns_a_404_instead_of_raising():
    fetcher = endpoints.Fetcher(
        min_interval=0,
        session=FakeSession(FakeResponse(status=404, raw=b"{}")),
        sleep=lambda s: None,
    )
    assert fetcher.get("u").status_code == 404