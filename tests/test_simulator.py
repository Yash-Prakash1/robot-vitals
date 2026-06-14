"""Tests that lock the simulator's demo narrative under the per-run, 7-joint model."""
from simulator import simulate_fleet


def _arm(fleet, robot_id):
    return next(a for a in fleet["arms"] if a["robot_id"] == robot_id)


def test_fleet_shape():
    fleet = simulate_fleet()
    assert fleet["days"] == 30
    assert fleet["runs_per_day"] == 4
    assert len(fleet["joints"]) == 7
    assert len(fleet["arms"]) == 8


def test_runs_per_day_and_all_joints():
    fleet = simulate_fleet()
    arm = _arm(fleet, "wx-01")
    assert len(arm["runs"]) == 30 * 4              # a check before every run, not once a day
    for run in arm["runs"][:5]:
        assert set(run["temps"].keys()) == set(fleet["joints"])  # every run reads all 7 joints
    assert len(arm["daily_temp_c"]) == 30
    assert len(arm["daily_current_a"]) == 30


def test_determinism():
    a = simulate_fleet(seed=1)
    b = simulate_fleet(seed=1)
    assert a["arms"][2]["daily_temp_c"][29]["elbow"] == b["arms"][2]["daily_temp_c"][29]["elbow"]


def test_later_runs_in_a_day_are_warmer():
    fleet = simulate_fleet()
    arm = _arm(fleet, "wx-01")
    day0 = [r for r in arm["runs"] if r["day"] == 0]
    # mean elbow temp of the last run of the day exceeds the first (intra-day warmup)
    assert day0[-1]["temps"]["elbow"] > day0[0]["temps"]["elbow"]


def test_thermal_creep_arm_elbow_climbs():
    fleet = simulate_fleet()
    creep = _arm(fleet, "wx-03")
    early = creep["daily_temp_c"][2]["elbow"]
    late = creep["daily_temp_c"][29]["elbow"]
    assert late - early > 8.0
    # a joint that is not the creep joint stays flat
    assert abs(creep["daily_temp_c"][29]["waist"] - creep["daily_temp_c"][2]["waist"]) < 3.0


def test_effort_rise_arm_shoulder_current_climbs():
    fleet = simulate_fleet()
    rise = _arm(fleet, "wx-06")
    early = rise["daily_current_a"][2]["shoulder"]
    late = rise["daily_current_a"][29]["shoulder"]
    assert (late - early) / early > 0.25


def test_acute_arm_spikes_on_one_run_only():
    fleet = simulate_fleet()
    acute = _arm(fleet, "wx-08")
    spike_runs = [r for r in acute["runs"] if r["day"] == 18 and r["run_index"] == 2]
    other_runs = [r for r in acute["runs"] if r["day"] == 18 and r["run_index"] != 2]
    assert spike_runs[0]["temps"]["elbow"] - max(r["temps"]["elbow"] for r in other_runs) > 12.0
    # the daily trend is barely disturbed: this is a per-run event, not drift
    assert acute["daily_temp_c"][18]["elbow"] < 70.0


def test_healthy_arm_stays_flat():
    fleet = simulate_fleet()
    healthy = _arm(fleet, "wx-01")
    elbow = [day["elbow"] for day in healthy["daily_temp_c"]]
    assert max(elbow) - min(elbow) < 3.0
