"""Tests for the WidowX hardware adapter: nine servos present as seven joints,
read through the documented DYNAMIXEL register path (via the simulated bus), and
feed straight into the gate.
"""
from interface import SimulatedDynamixelBus, WidowXAdapter
from quality_score import Verdict, evaluate_run


def _bus(servo_temps):
    return SimulatedDynamixelBus(temperatures_c=servo_temps)


def test_nine_servos_present_as_seven_joints():
    temps = {name: 50.0 for name, _id, _m in WidowXAdapter.SERVOS}
    adapter = WidowXAdapter(_bus(temps))
    joints = adapter.read_joint_temperatures()
    assert len(joints) == 7
    assert set(joints) == {"waist", "shoulder", "elbow", "forearm_roll",
                           "wrist_angle", "wrist_rotate", "gripper"}


def test_dual_servo_joint_takes_the_hotter_servo():
    temps = {name: 50.0 for name, _id, _m in WidowXAdapter.SERVOS}
    temps["elbow_1"] = 70.0
    temps["elbow_2"] = 64.0
    adapter = WidowXAdapter(_bus(temps))
    assert adapter.read_joint_temperatures()["elbow"] == 70.0  # the servo at risk


def test_joint_limits_are_per_model():
    limits = WidowXAdapter(_bus({n: 50.0 for n, _i, _m in WidowXAdapter.SERVOS})).joint_limits()
    assert limits["elbow"] == 80.0          # XM430-W350
    assert limits["wrist_rotate"] == 72.0   # XL430-W250
    assert limits["gripper"] == 72.0


def test_adapter_readings_feed_the_gate():
    temps = {name: 50.0 for name, _id, _m in WidowXAdapter.SERVOS}
    temps["elbow_1"] = 76.0
    adapter = WidowXAdapter(_bus(temps))
    report = evaluate_run("wx-07", "r", "2026-05-15T09:00:00",
                          adapter.read_joint_temperatures(), adapter.joint_limits())
    assert report.weakest_joint == "elbow"
    assert report.verdict is Verdict.QUARANTINE
