"""Tests for the k1 / b selection rule."""

from __future__ import annotations

from code_atlas.eval.sweep import DEFAULTS, choose_setting


def test_keeps_defaults_when_gain_is_below_margin() -> None:
    assert choose_setting({DEFAULTS: 0.300, (0.9, 0.5): 0.315}) == DEFAULTS


def test_takes_best_when_gain_reaches_margin() -> None:
    assert choose_setting({DEFAULTS: 0.300, (0.9, 0.5): 0.330}) == (0.9, 0.5)


def test_defaults_win_when_they_are_best() -> None:
    assert choose_setting({DEFAULTS: 0.300, (0.9, 0.5): 0.250}) == DEFAULTS


def test_tie_for_best_goes_to_first_in_grid_order() -> None:
    scores = {DEFAULTS: 0.200, (1.5, 0.25): 0.300, (0.6, 1.0): 0.300}
    assert choose_setting(scores) == (0.6, 1.0)
