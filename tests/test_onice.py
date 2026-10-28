"""Tests for the Phase 3 on-ice logic. They use a tiny made-up game, no real data.

Teams: home = 1, away = 2.
  Home: goalie 10, first line 11-15 (on the ice 0-60), second line 16-20 (60-120).
  Away: goalie 40, first line 21-25 (on the ice 0-60), second line 26-30 (60-120).
Goalies play 0-120.
"""

import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "src" / "nhl_pipeline" / "transform")
)

import build_onice  # noqa: E402
import onice  # noqa: E402

GAME = {"game_id": 1, "home_team_id": 1, "away_team_id": 2}
GOALIES = {10, 40}


def shift(player, team, start, end, period=1):
    return {
        "game_id": 1, "player_id": player, "team_id": team, "period": period,
        "start_game_seconds": start, "end_game_seconds": end,
    }


def game_shifts():
    rows = [shift(10, 1, 0, 120), shift(40, 2, 0, 120)]
    rows += [shift(p, 1, 0, 60) for p in range(11, 16)]
    rows += [shift(p, 1, 60, 120) for p in range(16, 21)]
    rows += [shift(p, 2, 0, 60) for p in range(21, 26)]
    rows += [shift(p, 2, 60, 120) for p in range(26, 31)]
    return rows


def event(event_id, t, event_type, code="1551", owner=None, period_type="REG"):
    return {
        "game_id": 1, "event_id": event_id, "sort_order": event_id, "period": 1,
        "period_type": period_type, "game_seconds": t, "event_type": event_type,
        "situation_code": code, "event_owner_team_id": owner,
    }


# ---- small helpers ----------------------------------------------------------


def test_parse_situation_code_gives_the_confirmed_digit_order():
    assert onice.parse_situation_code("1451") == {
        "away_goalie": 1, "away_skaters": 4, "home_skaters": 5, "home_goalie": 1,
    }
    for bad in (None, "", "155", "15511", "15x1"):
        assert onice.parse_situation_code(bad) is None


def test_rule_for_event_type():
    for stops_play in ("goal", "penalty", "delayed-penalty", "period-end", "game-end"):
        assert onice.rule_for(stops_play) == "B"
    for other in ("faceoff", "period-start", "shot-on-goal", "hit", "stoppage", "unknown"):
        assert onice.rule_for(other) == "A"


# ---- shifts -----------------------------------------------------------------


def test_clean_shifts_drops_exact_duplicates_marks_goalies_and_flags_conflicts():
    rows = [
        shift(11, 1, 0, 60),
        shift(11, 1, 0, 60),  # exact duplicate (the NHL gives it a different id)
        shift(10, 1, 0, 1200),
        shift(10, 1, 45, 114),  # overlaps the goalie's whole-period row, not identical
        shift(12, 1, 0, 60),
        shift(12, 1, 60, 90),  # touches but does not overlap
        shift(13, 1, None, 60),  # unusable
    ]
    cleaned = onice.clean_shifts(rows, goalie_ids={10})
    assert len(cleaned) == 5
    by_key = {(s["player_id"], s["start"], s["end"]): s for s in cleaned}
    assert by_key[(10, 0, 1200)]["is_goalie"] and by_key[(10, 0, 1200)]["has_conflict"]
    assert by_key[(10, 45, 114)]["has_conflict"]
    assert not by_key[(11, 0, 60)]["is_goalie"] and not by_key[(11, 0, 60)]["has_conflict"]
    assert not by_key[(12, 0, 60)]["has_conflict"] and not by_key[(12, 60, 90)]["has_conflict"]


def test_active_shifts_boundaries_for_both_rules():
    cleaned = onice.clean_shifts([shift(11, 1, 0, 60), shift(16, 1, 60, 120)], set())
    a = onice.active_shifts(cleaned, [0, 59, 60, 120], "A")
    b = onice.active_shifts(cleaned, [0, 59, 60, 120], "B")
    ids = lambda result, t: sorted(s["player_id"] for s in result[t])  # noqa: E731
    assert [ids(a, t) for t in (0, 59, 60, 120)] == [[11], [11], [16], []]
    assert [ids(b, t) for t in (0, 59, 60, 120)] == [[], [11], [11], [16]]


# ---- the per-event on-ice rows ----------------------------------------------


def build(events, shifts=None):
    cleaned = onice.clean_shifts(shifts or game_shifts(), GOALIES)
    return onice.build_event_on_ice(GAME, events, cleaned)


def test_each_event_type_uses_its_own_boundary_rule():
    rows = {r["event_type"]: r for r in build(
        [event(1, 60, "faceoff"), event(2, 60, "goal", owner=1)]
    )}
    assert rows["faceoff"]["home_skater_ids"] == [16, 17, 18, 19, 20]  # new line starts
    assert rows["goal"]["home_skater_ids"] == [11, 12, 13, 14, 15]  # old line was still on
    assert rows["goal"]["away_skater_ids"] == [21, 22, 23, 24, 25]
    assert rows["goal"]["home_goalie_ids"] == [10] and rows["goal"]["away_goalie_ids"] == [40]
    assert rows["faceoff"]["matches_situation"] and rows["goal"]["matches_situation"]
    assert rows["goal"]["rule"] == "B" and rows["faceoff"]["rule"] == "A"


def test_disagreement_missing_code_shootout_and_missing_clock():
    rows = build([
        event(1, 30, "shot-on-goal", code="1451"),  # away has 5 on ice, code says 4
        event(2, 31, "hit", code=None),
        event(3, 32, "shot-on-goal", period_type="SO"),
        {**event(4, 33, "hit"), "game_seconds": None},
    ])
    assert [r["event_id"] for r in rows] == [1, 2]
    assert rows[0]["matches_situation"] is False
    assert rows[0]["away_skaters_on_ice"] == 5 and rows[0]["away_skaters_code"] == 4
    assert rows[1]["matches_situation"] is None and rows[1]["home_skaters_code"] is None


def test_conflicting_shift_is_flagged_and_the_player_counted_once():
    shifts = game_shifts() + [shift(11, 1, 10, 50)]  # second, different shift for player 11
    row = build([event(1, 30, "hit")], shifts)[0]
    assert row["uses_conflicting_shift"] is True
    assert row["home_skater_ids"] == [11, 12, 13, 14, 15]
    assert row["home_skaters_on_ice"] == 5 and row["matches_situation"] is True


def test_events_come_back_in_the_nhl_order():
    rows = build([event(3, 90, "hit"), event(1, 60, "goal", owner=1), event(2, 60, "faceoff")])
    assert [r["event_id"] for r in rows] == [1, 2, 3]


# ---- plus/minus -------------------------------------------------------------


def test_plus_minus_counts_even_strength_and_shorthanded_but_not_power_play_goals():
    rows = build([
        event(1, 30, "goal", code="1551", owner=1),  # even strength, home scores
        event(2, 40, "goal", code="1451", owner=1),  # home power play: not counted
        event(3, 50, "goal", code="1541", owner=1),  # home shorthanded: counted
        event(4, 55, "goal", code="1560", owner=2),  # home goalie pulled, away scores: counted
    ])
    totals = onice.game_plus_minus(GAME, rows)
    assert {p: totals[p] for p in (11, 12, 13, 14, 15)} == {p: 1 for p in range(11, 16)}
    assert {p: totals[p] for p in (21, 22, 23, 24, 25)} == {p: -1 for p in range(21, 26)}
    assert 10 not in totals and 40 not in totals  # goalies get no plus/minus


def test_plus_minus_power_play_ignores_the_extra_attacker():
    rows = build([
        event(1, 30, "goal", code="0551", owner=1),  # away goalie pulled while short: home power play
        event(2, 40, "goal", code="0641", owner=2),  # away 6 skaters, no goalie, vs 4: away power play
    ])
    assert onice.game_plus_minus(GAME, rows) == {}
    rows = build([event(1, 50, "goal", code="0651", owner=2)])  # even-strength empty net: counts
    totals = onice.game_plus_minus(GAME, rows)
    assert {p: totals[p] for p in range(21, 26)} == {p: 1 for p in range(21, 26)}
    assert {p: totals[p] for p in range(11, 16)} == {p: -1 for p in range(11, 16)}


def test_plus_minus_ignores_penalty_shot_goals():
    rows = build([
        event(1, 30, "goal", code="1010", owner=1),  # home penalty shot: not counted
        event(2, 40, "goal", code="0101", owner=2),  # away penalty shot: not counted
    ])
    assert onice.game_plus_minus(GAME, rows) == {}


# ---- output schemas ---------------------------------------------------------


def test_output_rows_match_their_schemas():
    row = build([event(1, 30, "hit")])[0]
    assert set(row) == {name for name, _ in build_onice.SCHEMAS["event_on_ice"]}
    cleaned = onice.clean_shifts(game_shifts(), GOALIES)
    out = build_onice.shift_rows_for_output(cleaned)[0]
    assert set(out) == {name for name, _ in build_onice.SCHEMAS["shifts_clean"]}


def test_parquet_round_trip_with_list_columns(tmp_path):
    rows = build([event(1, 30, "hit"), event(2, 60, "goal", owner=1)])
    writer = build_onice.TableWriter(tmp_path / "event_on_ice.parquet", "event_on_ice")
    writer.write(rows)
    writer.close()
    table = pq.read_table(tmp_path / "event_on_ice.parquet")
    assert table.num_rows == 2
    assert table.column_names == [n for n, _ in build_onice.SCHEMAS["event_on_ice"]]
    assert table.column("home_skater_ids").to_pylist()[0] == [11, 12, 13, 14, 15]
    assert table.column("matches_situation").to_pylist() == [True, True]