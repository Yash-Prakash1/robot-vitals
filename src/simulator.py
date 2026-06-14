"""The degradation simulator. All data is synthetic and deterministic per seed.

Generates an 8-arm WidowX fleet over 30 days, several test runs per day (the
check runs before every run, not once a day), each reading all seven joints. Most
arms stay healthy; three carry one planted degradation each so the gate and the
maintenance layer have something real to catch: an elbow whose cooling slowly
degrades, a shoulder whose effort slowly rises (a bearing wearing), and one acute
hot run. Later runs in a day are warmer, because the arm heats up under continued
operation (AutoEval's 8-hour effect, in miniature). The real register reads this
stands in for are documented in interface.py.
"""

import random

# All constants and the fleet config come from config.json (single source of
# truth), via src/config.py.
from config import (
    BASE_CURRENT_A,
    BASE_TEMP_C,
    CANONICAL_SEED,
    CURRENT_NOISE_SIGMA_A,
    FLEET,
    INTRA_DAY_WARMUP_C,
    JOINT_NAMES,
    RUN_NOISE_SIGMA_C,
    RUNS_PER_DAY,
)


def _creep(cfg, joint, day):
    if cfg["profile"] != "thermal-creep" or joint != cfg["creep_joint"]:
        return 0.0
    if day < cfg["creep_onset_day"]:
        return 0.0
    return (day - cfg["creep_onset_day"]) * cfg["creep_rate_c_per_day"]


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


def simulate_fleet(seed=CANONICAL_SEED, days=30):
    """Return synthetic fleet readings, deterministic for a given seed.

    Each arm has, over the window: `runs` (every test run, with per-joint
    temperatures), `daily_temp_c` (the mean of each day's runs per joint, the
    thermal maintenance trend), and `daily_current_a` (a reference-motion current
    per joint per day, the effort maintenance trend). The trend uses the daily
    mean rather than the peak, because the mean is a cleaner trend signal (the
    peak of several noisy runs is skewed and noisier); the per-run gate still sees
    each individual run, including the hottest.
    """
    rng = random.Random(seed)
    arms = []
    for cfg in FLEET:
        runs, daily_temp, daily_current = [], [], []
        for day in range(days):
            day_runs = []
            for run_index in range(RUNS_PER_DAY):
                temps = {}
                for joint in JOINT_NAMES:
                    temps[joint] = (
                        BASE_TEMP_C[joint]
                        + _creep(cfg, joint, day)
                        + run_index * INTRA_DAY_WARMUP_C
                        + _acute_spike(cfg, joint, day, run_index)
                        + rng.gauss(0.0, RUN_NOISE_SIGMA_C)
                    )
                day_runs.append(temps)
                runs.append({"day": day, "run_index": run_index, "temps": temps})

            n = len(day_runs)
            daily_temp.append({j: sum(r[j] for r in day_runs) / n for j in JOINT_NAMES})
            daily_current.append({
                j: max(0.0, BASE_CURRENT_A[j] + _effort_rise(cfg, j, day)
                       + rng.gauss(0.0, CURRENT_NOISE_SIGMA_A))
                for j in JOINT_NAMES
            })

        arms.append({
            "robot_id": cfg["robot_id"],
            "profile": cfg["profile"],
            "runs": runs,
            "daily_temp_c": daily_temp,
            "daily_current_a": daily_current,
        })
    return {"days": days, "seed": seed, "runs_per_day": RUNS_PER_DAY,
            "joints": list(JOINT_NAMES), "arms": arms}
