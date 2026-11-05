import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_goal_shot_type_and_goalie_rows import edge_distance, fill_status, tally_skater_games  # noqa: E402


def row(start, end):
    return {"start": start, "end": end}


def goal(player, shot_type=None):
    return {"event_type": "goal", "scoring_player_id": player, "shooting_player_id": None, "shot_type": shot_type}


def shot(player):
    return {"event_type": "shot-on-goal", "scoring_player_id": None, "shooting_player_id": player, "shot_type": "wrist"}


def test_fill_status_kept_fillable_uncovered():
    kept = [row(2400, 2636)]
    dropped = [row(2400, 3600)]
    assert fill_status(kept, dropped, 2500) == "kept"
    assert fill_status(kept, dropped, 2777) == "fillable"
    assert fill_status(kept, [], 2777) == "uncovered"
    assert fill_status([], dropped, 3700) == "uncovered"


def test_tally_separates_goal_without_shot_type():
    shots = [shot(1), goal(1), shot(2), goal(3, shot_type="wrist"), goal(4)]
    box = {1: 2, 2: 1, 3: 1, 4: 0, 5: 0}
    tally = tally_skater_games(shots, box)
    # player 1: events 2, box 2, difference 0, goal has no shot type -> (True, 0)
    # player 4: events 1, box 0 -> (True, +1)
    assert tally[(True, 0)] == 1
    assert tally[(True, 1)] == 1
    assert tally[(False, 0)] == 3


def test_tally_ignores_goalie_shooters():
    shots = [shot(99)]
    assert tally_skater_games(shots, {1: 0}) == {(False, 0): 1}


def test_end_is_included_only_for_goals():
    kept = [row(2400, 2636)]
    assert fill_status(kept, [], 2636) == "uncovered"
    assert fill_status(kept, [], 2636, end_inclusive=True) == "kept"
    assert fill_status(kept, [], 2400) == "kept"


def test_edge_distance():
    assert edge_distance([row(100, 200), row(500, 600)], 210) == 10
    assert edge_distance([], 5) is None