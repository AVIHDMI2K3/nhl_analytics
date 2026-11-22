"""Tests for the helpers of scripts/diagnose_skater_gap.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import diagnose_skater_gap as d  # noqa: E402


def attempt(kind, matches, ours_for, ours_against):
    return {
        "attempt_type": kind,
        "matches_situation": matches,
        "skater_ids_for": ours_for,
        "skater_ids_against": ours_against,
    }


def test_mismatched_attempts_are_counted_for_every_skater_listed_on_the_ice():
    attempts = [
        attempt("shot-on-goal", False, [1, 2], [3]),
        attempt("goal", False, [1], []),
        attempt("missed-shot", True, [1, 2], [3]),
        attempt("faceoff", False, [9], []),
        attempt("blocked-shot", None, [2], []),
    ]
    assert d.mismatched_attempts_by_player(attempts) == {1: 2, 2: 1, 3: 1}


def test_buckets_and_summary():
    assert [d.bucket_of(n) for n in (0, 2, 3, 10, 11, 400)] == [
        "none",
        "1-2",
        "3-5",
        "6-10",
        "11 or more",
        "11 or more",
    ]
    summary = d.summarize([(0, 0), (0, 3), (4, -2), (50, 9)])
    assert summary["none"] == (2, 1, 1, 1.5) and summary["3-5"] == (1, 0, 1, 2.0)
    assert summary["11 or more"] == (1, 0, 0, 9.0) and summary["1-2"] == (0, 0, 0, None)
