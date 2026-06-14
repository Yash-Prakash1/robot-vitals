"""Tests for the per-joint maintenance layer.

The headline property: CUSUM confirms a drift before the trend crosses the action
cap (the lead time that buys a scheduled fix). Also checks the watch threshold
that keeps flat-but-noisy healthy joints from flagging, the per-joint limit, and
the full canonical-fleet story (only the two planted joints flag).
"""
import pytest

from maintenance import (
    EFFORT_ACTION_CAP_SCORE,
    analyze_effort,
    analyze_fleet,
    analyze_thermal,
    effort_performance_score,
    pooled_sigma,
)
from simulator import simulate_fleet

XM, XL = 80.0, 72.0


def _ripple(d):
    return 0.2 if d % 2 == 0 else -0.2


def test_effort_performance_score_scale():
    assert effort_performance_score(0.30, 0.30) == pytest.approx(100.0)
    assert effort_performance_score(0.375, 0.30) == pytest.approx(50.0)   # +25 pct, the cap
    assert effort_performance_score(0.45, 0.30) == pytest.approx(0.0)
    assert EFFORT_ACTION_CAP_SCORE == 50.0


def test_pooled_sigma_positive():
    assert pooled_sigma([[100 + _ripple(i) for i in range(10)] for _ in range(8)]) > 0.0


def test_flat_healthy_thermal_stays_stable():
    series = [58.0 + _ripple(d) for d in range(30)]   # warm but flat, below the 60 C ceiling
    r = analyze_thermal(series, noise_sigma=0.3, limit_c=XM)
    assert r["status"] == "stable"
    assert r["cusum_detected_day"] is None


def test_watch_threshold_suppresses_cusum_only_drift():
    # a sustained shift that CUSUM detects, but that does not drop the score past
    # the watch level (the temperature stays in the healthy band), must NOT flag.
    series = [58.0 + _ripple(d) + (0.0 if d < 10 else 2.5) for d in range(30)]
    r = analyze_thermal(series, noise_sigma=0.3, limit_c=XM)
    assert r["cusum_detected_day"] is not None   # CUSUM did detect the shift
    assert r["status"] == "stable"               # but the score never dropped past the watch level
    assert "drifting" not in r["status_by_day"]


def test_thermal_ramp_is_caught_before_the_cap():
    series = [59.0 + _ripple(d) + max(0, d - 10) * 1.2 for d in range(30)]
    r = analyze_thermal(series, noise_sigma=0.4, limit_c=XM)
    assert r["status"] == "alarm"
    assert r["cusum_detected_day"] < r["cap_cross_day"]


def test_thermal_ramp_uses_the_joint_limit():
    # the same temperatures reach the cap sooner against the lower XL430 limit
    series = [51.0 + _ripple(d) + max(0, d - 10) * 1.2 for d in range(30)]
    xl = analyze_thermal(series, noise_sigma=0.4, limit_c=XL)
    assert xl["status"] == "alarm"               # crosses its 72 C-anchored cap


def test_effort_ramp_is_caught_before_the_cap():
    series = [0.30 + (0.005 if d % 2 == 0 else -0.005) + max(0, d - 10) * 0.005 for d in range(30)]
    r = analyze_effort(series, noise_sigma=0.008)
    assert r["status"] == "alarm"
    assert r["cusum_detected_day"] < r["cap_cross_day"]


def test_canonical_fleet_flags_only_the_two_planted_joints():
    fleet = simulate_fleet()  # canonical seed
    res = analyze_fleet(fleet["arms"], fleet["joints"], fleet["days"])
    flags = []
    for rid, r in res.items():
        for joint, ch in r["joints"].items():
            for chan in ("thermal", "effort"):
                if ch[chan]["status"] != "stable":
                    flags.append((rid, joint, chan, ch[chan]))
    keys = sorted((f[0], f[1], f[2]) for f in flags)
    assert keys == [("wx-03", "elbow", "thermal"), ("wx-06", "shoulder", "effort")]
    for rid, joint, chan, ch in flags:
        assert ch["status"] == "alarm"
        assert ch["cusum_detected_day"] < ch["cap_cross_day"]   # detected before the cap
