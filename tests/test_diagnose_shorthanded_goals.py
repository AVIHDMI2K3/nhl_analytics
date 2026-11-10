"""Tests for the helper of scripts/diagnose_shorthanded_goals.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "nhl_pipeline" / "transform"))
sys.path.insert(0, str(ROOT / "scripts"))

import diagnose_shorthanded_goals as d  # noqa: E402


def test_disagreeing_lists_only_the_differences_with_missing_ours_as_zero():
    nhl = {(1, 10): 1, (1, 11): 0, (2, 10): 2}
    ours = {(1, 10): 1, (2, 10): 1}
    assert d.disagreeing(ours, nhl) == [(2, 10, 1, 2)]
    assert d.disagreeing({}, {(1, 10): 1}) == [(1, 10, 0, 1)]