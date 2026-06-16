"""The degradation simulator. All data is synthetic and deterministic per seed.

Generates an 8-arm WidowX fleet over 30 days, several test runs per day (the gate
runs before every run, not once a day), each reading all seven joints.

Actuators heat up with continued use. Before a run, if continuing would push any
joint into its data-at-risk band, the robot **rests**: it cools the actuators back
to baseline and then collects. So gradual heat is never COLLECTED corrupt; the cost
is the resting time (counted per day). A sudden transient (the acute fault) can
still read hot mid-run, which the gate cannot foresee to rest away, so it is flagged
REST and rejected rather than prevented.

Most arms stay healthy. Three carry one planted fault so the gate and the
maintenance layer have something real to catch:
  - an elbow whose motor heats FASTER over time (more friction, more heat per run).
    Resting cannot cure it, the floor it cools to is fine, it just heats faster, so
    it needs maintenance. This is what the daily trend (on the mean temperature) is
    for, and what drives rests/day up.
  - a shoulder whose effort (reference current) slowly rises (a bearing wearing).
  - one acute hot run (a transient the per-run gate catches, that rest cannot
    foresee).

The real register reads this stands in for are documented in interface.py.
"""

import random

# All constants and the fleet config come from config.json (single source of
# truth), via src/config.py.
from config import (
    BASE_CURRENT_A,
    BASE_TEMP_C,
    CANONICAL_SEED,
    CURRENT_NOISE_SIGMA_A,
    DATA_AT_RISK_OFFSET_C,
    FLEET,
    INTRA_DAY_WARMUP_C,
    JOINT_LIMIT_C,
    JOINT_NAMES,
    RUN_NOISE_SIGMA_C,
    RUNS_PER_DAY,
)


def _warmup(cfg, joint, day):
    """Heat added to an actuator per run of continued use. A healthy joint heats a
    fixed amount each run; the thermal-fault joint heats FASTER as it degrades, which
    is the part rest cannot cure (the floor is fine, the rate of climb is not)."""
    base = INTRA_DAY_WARMUP_C
    if (cfg["profile"] == "thermal-creep" and joint == cfg["creep_joint"]
            and day >= cfg["creep_onset_day"]):
        base += (day - cfg["creep_onset_day"]) * cfg["fault_heat_c_per_day"]
    return base


def _effort_rise(cfg, joint, day):
    if cfg["profile"] != "effort-rise" or joint != cfg["effort_joint"]:
        return 0.0
    if day < cfg["effort_onset_day"]:
        return 0.0
    return (day - cfg["effort_onset_day"]) * cfg["effort_rate_a_per_day"]


def _acute_spike(cfg, joint, day, run_index):
    if cfg["profile"] != "acute-hot-start":
        return 0.0
    if day == cfg["acute_day"] and run_index == cfg["acute_run"] and joint == cfg["acute_joint"]:
        return cfg["acute_spike_c"]
    return 0.0


# the gate rests an actuator at this temperature so the run never reaches corruption
REST_LINE_C = {j: JOINT_LIMIT_C[j] - DATA_AT_RISK_OFFSET_C for j in JOINT_NAMES}


def simulate_fleet(seed=CANONICAL_SEED, days=30):
    """Return synthetic fleet readings, deterministic for a given seed.

    Each arm has, over the window: `runs` (every test run, with per-joint
    temperatures and whether the robot rested before it), `daily_temp_c` (the mean
    of each day's recorded runs per joint, the thermal maintenance trend),
    `daily_rests` (rests inserted that day, the throughput cost), and
    `daily_current_a` (a reference-motion current per joint per day, the effort
    trend). The trend uses the daily mean because a faster-heating motor runs hotter
    on average even with resting, so the mean carries the drift; the per-run gate
    still sees each individual run.
    """
    rng = random.Random(seed)
    arms = []
    for cfg in FLEET:
        runs, daily_temp, daily_current, daily_rests = [], [], [], []
        for day in range(days):
            warmup = {j: _warmup(cfg, j, day) for j in JOINT_NAMES}
            temp = {j: BASE_TEMP_C[j] for j in JOINT_NAMES}   # rested baseline, deterministic
            rests = 0
            day_runs = []
            for run_index in range(RUNS_PER_DAY):
                # The gate: if continuing would push any joint into its data-at-risk
                # band, rest first (cool to baseline) so the run is never recorded
                # too hot. When even a rested run would be at risk (the fault is past
                # saving), resting no longer helps; that is the maintenance regime.
                rested = any(temp[j] + warmup[j] >= REST_LINE_C[j] for j in JOINT_NAMES)
                if rested:
                    temp = {j: BASE_TEMP_C[j] for j in JOINT_NAMES}
                    rests += 1
                temps = {}
                for j in JOINT_NAMES:
                    temp[j] += warmup[j]   # the actuator heats during the run
                    temps[j] = (temp[j] + _acute_spike(cfg, j, day, run_index)
                                + rng.gauss(0.0, RUN_NOISE_SIGMA_C))
                day_runs.append(temps)
                runs.append({"day": day, "run_index": run_index, "temps": temps, "rested": rested})

            n = len(day_runs)
            daily_temp.append({j: sum(r[j] for r in day_runs) / n for j in JOINT_NAMES})
            daily_rests.append(rests)
            # the effort channel reads the reference current once per run and takes the
            # daily mean, in step with the temperature channel, so both trends carry the
            # same low per-day noise (a single-sample current is too noisy to trend cleanly).
            cur_samples = [
                {j: BASE_CURRENT_A[j] + _effort_rise(cfg, j, day) + rng.gauss(0.0, CURRENT_NOISE_SIGMA_A)
                 for j in JOINT_NAMES}
                for _ in range(RUNS_PER_DAY)
            ]
            daily_current.append({
                j: max(0.0, sum(s[j] for s in cur_samples) / RUNS_PER_DAY) for j in JOINT_NAMES
            })

        arms.append({
            "robot_id": cfg["robot_id"],
            "profile": cfg["profile"],
            "runs": runs,
            "daily_temp_c": daily_temp,
            "daily_rests": daily_rests,
            "daily_current_a": daily_current,
        })
    return {"days": days, "seed": seed, "runs_per_day": RUNS_PER_DAY,
            "joints": list(JOINT_NAMES), "arms": arms}
