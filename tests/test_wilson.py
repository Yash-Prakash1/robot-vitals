"""Tests for the Wilson score interval.

The headline test is that 20 of 20 is NOT [1.0, 1.0]. That is the whole reason
to prefer Wilson over the naive normal approximation for small-sample evals.
"""
import math

import pytest

from wilson import wilson_interval, wilson_lower_bound


def test_perfect_score_is_not_one_to_one():
    iv = wilson_interval(20, 20)
    assert iv.high == 1.0
    assert iv.low < 0.9                              # nowhere near a false 100 percent
    assert math.isclose(iv.low, 0.8389, abs_tol=0.005)


def test_zero_successes_is_not_zero_to_zero():
    iv = wilson_interval(0, 20)
    assert iv.low == 0.0
    assert iv.high > 0.0
    assert math.isclose(iv.high, 0.1611, abs_tol=0.005)


def test_interval_stays_within_unit_range():
    for n in range(1, 60):
        for s in range(0, n + 1):
            iv = wilson_interval(s, n)
            assert 0.0 <= iv.low <= iv.high <= 1.0


def test_symmetric_at_one_half():
    iv = wilson_interval(10, 20)
    assert math.isclose(iv.center, 0.5, abs_tol=1e-9)
    assert math.isclose(iv.point, 0.5, abs_tol=1e-9)
    assert math.isclose(0.5 - iv.low, iv.high - 0.5, abs_tol=1e-9)


def test_asymmetric_near_edge():
    iv = wilson_interval(18, 20)                     # point estimate 0.9
    lower_tail = iv.point - iv.low
    upper_tail = iv.high - iv.point
    assert lower_tail > upper_tail                   # longer tail toward the center


def test_width_shrinks_with_more_trials():
    narrow = wilson_interval(100, 200).width         # p = 0.5, n = 200
    wide = wilson_interval(10, 20).width             # p = 0.5, n = 20
    assert narrow < wide


def test_lower_bound_matches_interval():
    assert wilson_lower_bound(15, 20) == wilson_interval(15, 20).low


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        wilson_interval(0, 0)
    with pytest.raises(ValueError):
        wilson_interval(21, 20)
    with pytest.raises(ValueError):
        wilson_interval(-1, 20)
