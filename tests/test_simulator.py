"""Tests that lock the simulator's demo narrative under the per-run, 7-joint model."""
from config import CORRUPTION_OFFSET_C, DATA_AT_RISK_OFFSET_C, JOINT_LIMIT_C
from maintenance import analyze_fleet
from quality_score import Verdict, evaluate_run
from simulator import simulate_fleet

# the heat ladder, derived from config (single source), not hardcoded
CORRUPTION = JOINT_LIMIT_C["elbow"] - CORRUPTION_OFFSET_C   # 74 C
AT_RISK = JOINT_LIMIT_C["elbow"] - DATA_AT_RISK_OFFSET_C    # 72 C


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


def test_healthy_arms_never_rest():
    # a healthy joint heats a fixed, small amount and never approaches the data-at-risk
    # line, so the robot never has to stop and cool: full throughput, zero cost. Checked
    # for the whole healthy cohort, not a sample of one.
    for arm in simulate_fleet()["arms"]:
        if arm["profile"] != "healthy":
            continue
        assert sum(arm["daily_rests"]) == 0
        assert not any(r["rested"] for r in arm["runs"])
        assert max(r["temps"]["elbow"] for r in arm["runs"]) < AT_RISK   # never enters the at-risk band


def test_fault_arm_rests_climb_as_the_cost():
    # the faster-heating elbow forces the robot to rest more and more to stay cool:
    # rests/day is the throughput cost, ~0 early, climbing as the fault worsens.
    creep = _arm(simulate_fleet(), "wx-03")
    assert sum(creep["daily_rests"][:12]) == 0          # full speed before the fault bites
    assert max(creep["daily_rests"]) >= 3               # resting heavily once it does
    assert creep["daily_rests"][-1] > creep["daily_rests"][12]


def test_gate_resting_prevents_corrupt_data_until_quarantine():
    # the gate rests the actuator so a run is never COLLECTED at or above the corruption
    # line while the joint is serviceable: corruption appears strictly AFTER the
    # maintenance layer has quarantined it, so a pull always precedes any bad data.
    fleet = simulate_fleet()
    creep = _arm(fleet, "wx-03")
    quar = analyze_fleet(fleet["arms"], fleet["joints"], fleet["days"])["wx-03"]["joints"]["elbow"]["thermal"]["cap_cross_day"]
    assert max(r["temps"]["elbow"] for r in creep["runs"] if r["day"] <= quar) < CORRUPTION
    first_corrupt = next((r["day"] for r in creep["runs"] if r["temps"]["elbow"] >= CORRUPTION), None)
    assert first_corrupt == 28          # precise canonical onset (locks the gate guarantee)
    assert first_corrupt > quar         # the pull (day 27) precedes any corruption


def test_acute_spike_is_caught_by_the_gate_not_the_trend():
    # the acute spike is a sudden transient the gate cannot foresee to rest: it is
    # recorded hot and flagged REST (rejected), while the daily trend stays calm.
    fleet = simulate_fleet()
    acute = _arm(fleet, "wx-08")
    spike = next(r for r in acute["runs"] if r["day"] == 18 and r["run_index"] == 2)
    assert spike["temps"]["elbow"] >= CORRUPTION        # it does read above corruption
    assert spike["rested"] is False                      # rest could not foresee it
    assert evaluate_run("wx-08", "r", "t", spike["temps"], JOINT_LIMIT_C).verdict is Verdict.REST
    # the daily trend treats it as a one-off, not drift: wx-08 never flags
    res = analyze_fleet(fleet["arms"], fleet["joints"], fleet["days"])
    assert res["wx-08"]["joints"]["elbow"]["thermal"]["status"] == "stable"


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
