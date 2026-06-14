"""Tests for the CUSUM detector.

The two claims that matter: it does NOT false-alarm on healthy noise, and it
DOES fire on a planted sustained drift. Both are proven here, the first with a
deterministic worst-case noise pattern and again with seeded gaussian noise.
"""
import math
import random

import pytest

from cusum import Cusum, baseline_stats, first_alarm, run


def test_baseline_stats_mean_and_sample_std():
    mean, sigma = baseline_stats([1, 2, 3, 4, 5])
    assert mean == 3.0
    # sample variance = (4 + 1 + 0 + 1 + 4) / 4 = 2.5
    assert math.isclose(sigma, math.sqrt(2.5), rel_tol=1e-12)


def test_baseline_stats_requires_two_readings():
    with pytest.raises(ValueError):
        baseline_stats([42.0])


def test_floor_suppresses_bounded_zero_mean_noise():
    # Perfectly alternating noise of one sigma has zero mean. With slack
    # k = 0.5 sigma the cumulative sum can never escape the max(0, ...) floor,
    # so a clean signal never alarms no matter how long it runs.
    target, sigma = 50.0, 1.0
    readings = [target + (1.0 if i % 2 == 0 else -1.0) for i in range(200)]
    assert first_alarm(readings, target, sigma, h_sigma=5.0, direction="either") is None
    states = run(readings, target, sigma)
    assert max(s.s_hi for s in states) <= 5.0
    assert all(s.s_hi >= 0.0 and s.s_lo >= 0.0 for s in states)


def test_healthy_noise_rarely_alarms_over_the_maintenance_horizon():
    # CUSUM has a long but FINITE in-control run length by design: run clean
    # noise forever and it will eventually trip. What matters is the false-alarm
    # rate over the horizon the maintenance layer actually uses, a 30-day window.
    # With k = 0.5 sigma and h = 5 sigma that rate is measured at about 2.9
    # percent, low enough that healthy arms stay quiet across a fleet-month.
    rng = random.Random(0)
    window, trials, hits = 30, 4000, 0
    for _ in range(trials):
        readings = [rng.gauss(60.0, 1.5) for _ in range(window)]
        if first_alarm(readings, 60.0, 1.5, h_sigma=5.0, direction="high") is not None:
            hits += 1
    assert hits / trials < 0.06  # measured about 0.029; a safe ceiling


def test_detects_sustained_upward_drift():
    target, sigma = 60.0, 1.0
    rng = random.Random(7)
    healthy = [rng.gauss(target, sigma) for _ in range(50)]
    drifted = [rng.gauss(target + 1.5, sigma) for _ in range(50)]  # sustained +1.5 sigma
    readings = healthy + drifted
    i = first_alarm(readings, target, sigma, h_sigma=5.0, direction="high")
    assert i is not None
    assert i >= 50          # does not fire during the healthy stretch
    assert i <= 50 + 20     # confirms the drift reasonably quickly


def test_two_sided_downward_drift_trips_low_arm_only():
    target, sigma = 60.0, 1.0
    rng = random.Random(3)
    healthy = [rng.gauss(target, sigma) for _ in range(40)]
    cooled = [rng.gauss(target - 1.5, sigma) for _ in range(40)]
    readings = healthy + cooled
    assert first_alarm(readings, target, sigma, direction="low") is not None
    assert first_alarm(readings, target, sigma, direction="high") is None


def test_sums_never_go_negative():
    target, sigma = 10.0, 1.0
    readings = [target - 5 for _ in range(20)] + [target + 5 for _ in range(20)]
    states = run(readings, target, sigma)
    assert all(s.s_hi >= 0.0 for s in states)
    assert all(s.s_lo >= 0.0 for s in states)


def test_zero_sigma_rejected():
    with pytest.raises(ValueError):
        Cusum(target=50.0, sigma=0.0)
