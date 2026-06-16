"""Tests for the per-run thermal gate, now per joint with per-joint limits.

Covers the honest scoring curve against each joint's own limit (and the specific
bug it fixes), the collect/rest verdict, weakest-link aggregation across joints,
and the episode stamp.
"""
import json

import pytest

from quality_score import (
    Verdict,
    evaluate_run,
    thermal_headroom_score,
    thermal_verdict,
    worst_verdict,
)

# limits: XM430-W350 joints to 80 C, XL430-W250 joints to 72 C
XM, XL = 80.0, 72.0


def test_scoring_curve_xm430():
    assert thermal_headroom_score(60.0, XM) == 100.0
    assert thermal_headroom_score(80.0, XM) == 0.0
    assert thermal_headroom_score(70.0, XM) == 50.0
    assert thermal_headroom_score(65.0, XM) == 75.0


def test_scoring_curve_xl430_uses_its_own_limit():
    # XL430 ceiling is 72 minus the 20 C band = 52 C
    assert thermal_headroom_score(52.0, XL) == 100.0
    assert thermal_headroom_score(72.0, XL) == 0.0
    assert thermal_headroom_score(62.0, XL) == 50.0
    assert thermal_headroom_score(66.0, XL) == 30.0


def test_the_flagged_bug_is_fixed():
    # a healthy joint at 61 C on an 80 C limit must read healthy (95), not ~35
    assert thermal_headroom_score(61.0, XM) == pytest.approx(95.0)
    assert thermal_headroom_score(61.0, XM) >= 90.0


def test_verdict_collect_or_rest_scales_with_the_limit():
    # collect below the data-at-risk line (limit - 8), rest at or above it
    assert thermal_verdict(71.0, XM) is Verdict.COLLECT      # below 72
    assert thermal_verdict(72.0, XM) is Verdict.REST         # 80 - 8, the rest line
    assert thermal_verdict(76.0, XM) is Verdict.REST
    # the XL430 joint rests earlier, against its lower 72 C limit (line at 64)
    assert thermal_verdict(63.0, XL) is Verdict.COLLECT      # below 64
    assert thermal_verdict(64.0, XL) is Verdict.REST         # 72 - 8
    # the boundary is strict (collect strictly below the line); lock it tightly
    assert thermal_verdict(71.999, XM) is Verdict.COLLECT
    assert thermal_verdict(63.999, XL) is Verdict.COLLECT


def test_worst_verdict_is_weakest_link():
    assert worst_verdict([Verdict.COLLECT, Verdict.REST, Verdict.COLLECT]) is Verdict.REST
    assert worst_verdict([Verdict.COLLECT, Verdict.COLLECT]) is Verdict.COLLECT


def _limits(temps):
    # helper: XL430 limit for wrist_rotate and gripper, XM430 for the rest
    return {j: (XL if j in ("wrist_rotate", "gripper") else XM) for j in temps}


def test_gate_is_the_weakest_joint():
    temps = {"waist": 50.0, "shoulder": 55.0, "elbow": 74.0, "gripper": 41.0}
    report = evaluate_run("wx-01", "wx-01-d00-r0", "2026-05-15T09:00:00", temps, _limits(temps))
    assert report.weakest_joint == "elbow"
    assert report.gate_score == thermal_headroom_score(74.0, XM)   # 30.0
    assert report.verdict is Verdict.REST
    # the cool joints stay at full marks; the gate is the minimum, not the mean
    assert report.health_average > report.gate_score


def test_xl430_joint_can_set_the_gate_against_its_lower_limit():
    # a gripper at 67 C is fine for an 80 C limit but past the rest line for its 72 C limit
    temps = {"elbow": 60.0, "gripper": 67.0}
    report = evaluate_run("wx-01", "r", "2026-05-15T09:00:00", temps, _limits(temps))
    assert report.weakest_joint == "gripper"
    assert report.verdict is Verdict.REST


def test_all_healthy_collects():
    temps = {"waist": 50.0, "elbow": 58.0, "gripper": 40.0}
    report = evaluate_run("wx-01", "r", "2026-05-15T09:00:00", temps, _limits(temps))
    assert report.gate_score == 100.0
    assert report.verdict is Verdict.COLLECT


def test_stamp_is_complete_and_json_serializable():
    temps = {"waist": 50.0, "elbow": 72.0, "gripper": 41.0}
    report = evaluate_run("wx-03", "wx-03-d26-r3", "2026-06-10T15:00:00", temps, _limits(temps))
    stamp = report.to_stamp()
    for key in ("robot_id", "run_id", "timestamp", "quality_score", "verdict",
                "weakest_joint", "health_average", "joints"):
        assert key in stamp
    assert stamp["weakest_joint"] == "elbow"
    rt = json.loads(json.dumps(stamp))
    assert rt["joints"]["elbow"]["temp_c"] == 72.0
    assert rt["joints"]["elbow"]["verdict"] == "REST"


def test_empty_temps_rejected():
    with pytest.raises(ValueError):
        evaluate_run("wx-01", "r", "t", {}, {})
