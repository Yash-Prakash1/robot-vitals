"""Produce the canonical synthetic dataset the dashboard reads.

Wires the three layers together over the simulated fleet:
  - the per-run gate (quality_score) on each day's pre-flight temperatures,
  - the thermal and effort maintenance channels (maintenance) on the longitudinal
    settling temperatures and reference currents.

Writes three files into docs/:
  - data.json: pretty, for humans to inspect,
  - data.js:   `window.FLEET_DATA = {...};`, the baked reference fleet, included
    with a local <script> tag so it works even when opened from the file system
    (no fetch, no backend, no build step), per the zero-friction deployment rule.
  - config.js: `window.RV_CONFIG = {...};`, the contents of config.json, so the
    browser engine (docs/engine.js) reads the exact same constants the Python
    core does. This is what keeps the two implementations from drifting: there is
    one source of truth, config.json, and both sides read it.

All data is synthetic. The real register reads it stands in for are documented in
interface.py. Run from the repo root: python3 src/generate_dataset.py
"""

import json
import os
from datetime import timedelta

from config import (
    BASELINE_DAYS,
    CUSUM_H_SIGMA,
    CUSUM_K_SIGMA,
    EFFORT_ACTION_CAP_PCT,
    EFFORT_ACTION_CAP_SCORE,
    HEALTHY_BAND_C,
    JOINT_LIMIT_C,
    JOINTS,
    MODEL_TEMPERATURE_LIMIT_C,
    QUARANTINE_OFFSET_C,
    THERMAL_ACTION_CAP_SCORE,
    WARN_OFFSET_C,
)
from config import CONFIG as CONFIG_RAW
from config import START_DATE
from maintenance import analyze_fleet
from quality_score import evaluate_run
from simulator import CANONICAL_SEED, simulate_fleet

# The whole pipeline in one place, in execution order:
#   simulate_fleet      -> synthetic per-run temps and daily trends (simulator.py)
#   evaluate_run        -> per-run gate score and verdict, one per test run (quality_score.py)
#   analyze_fleet       -> CUSUM drift status per joint per channel (maintenance.py)
#   write data.js/json  -> the baked dataset the dashboard reads
#   write config.js     -> config.json for the browser engine (single source of truth)


def build_dataset(seed=CANONICAL_SEED, days=30):
    fleet = simulate_fleet(seed=seed, days=days)
    joints = fleet["joints"]
    dates = [(START_DATE + timedelta(days=d)).isoformat() for d in range(days)]
    maintenance = analyze_fleet(fleet["arms"], joints, days)

    verdict_counts = {"PASS": 0, "WARN": 0, "QUARANTINE": 0}
    robots = []
    for arm in fleet["arms"]:
        robot_id = arm["robot_id"]

        runs_out = []
        for r in arm["runs"]:
            day, run_index = r["day"], r["run_index"]
            run_id = f"{robot_id}-d{day:02d}-r{run_index}"
            timestamp = f"{dates[day]}T{9 + run_index * 2:02d}:00:00"
            report = evaluate_run(robot_id, run_id, timestamp, r["temps"], JOINT_LIMIT_C)
            verdict_counts[report.verdict.value] += 1
            runs_out.append({
                "run_id": run_id,
                "day": day,
                "run_index": run_index,
                "date": dates[day],
                "timestamp": timestamp,
                "temps_c": {j: round(t, 1) for j, t in r["temps"].items()},
                "gate_score": round(report.gate_score, 1),
                "verdict": report.verdict.value,
                "weakest_joint": report.weakest_joint,
            })

        joint_maint = maintenance[robot_id]["joints"]
        flags = []
        for j, ch in joint_maint.items():
            for chan in ("thermal", "effort"):
                if ch[chan]["status"] != "stable":
                    flags.append({"joint": j, "channel": chan, "status": ch[chan]["status"],
                                  "detected_day": ch[chan]["cusum_detected_day"],
                                  "cap_cross_day": ch[chan]["cap_cross_day"]})

        robots.append({
            "robot_id": robot_id,
            "profile": arm["profile"],
            "runs": runs_out,
            "maintenance": joint_maint,
            "flags": flags,
        })

    joint_defs = [{"name": j["name"], "model": j["model"],
                   "limit_c": JOINT_LIMIT_C[j["name"]], "servos": j.get("servos", 1)}
                  for j in JOINTS]

    return {
        "meta": {
            "generated_note": (
                "Synthetic data demonstrating the protocol. The real register "
                "reads (DYNAMIXEL Present Temperature and Present Current) are "
                "documented in src/interface.py."
            ),
            "fleet_size": len(robots),
            "days": days,
            "runs_per_day": fleet["runs_per_day"],
            "start_date": dates[0],
            "end_date": dates[-1],
            "dates": dates,
            "joints": joint_defs,
            "verdict_counts": verdict_counts,
            "thresholds": {
                "servo_temp_limit_c": dict(MODEL_TEMPERATURE_LIMIT_C),  # sourced (datasheet)
                "healthy_band_c": HEALTHY_BAND_C,              # illustrative
                "warn_offset_c": WARN_OFFSET_C,                # illustrative
                "quarantine_offset_c": QUARANTINE_OFFSET_C,    # illustrative
                "thermal_action_cap_score": THERMAL_ACTION_CAP_SCORE,  # illustrative
                "effort_action_cap_score": EFFORT_ACTION_CAP_SCORE,    # illustrative
                "effort_action_cap_pct": EFFORT_ACTION_CAP_PCT,        # illustrative
                "cusum_k_sigma": CUSUM_K_SIGMA,
                "cusum_h_sigma": CUSUM_H_SIGMA,
                "baseline_days": BASELINE_DAYS,
            },
        },
        "robots": robots,
    }


def main():
    dataset = build_dataset()
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    os.makedirs(docs_dir, exist_ok=True)

    json_path = os.path.join(docs_dir, "data.json")
    with open(json_path, "w") as f:
        json.dump(dataset, f, indent=2)

    js_path = os.path.join(docs_dir, "data.js")
    with open(js_path, "w") as f:
        f.write("// Generated by src/generate_dataset.py. Do not edit by hand.\n")
        f.write("// Synthetic data; see src/interface.py for the real register reads.\n")
        f.write("window.FLEET_DATA = ")
        json.dump(dataset, f, separators=(",", ":"))
        f.write(";\n")

    # Emit config.json for the browser engine, so docs/engine.js reads the exact
    # same constants as the Python core. config.json is the single source of truth.
    config_path = os.path.join(docs_dir, "config.js")
    with open(config_path, "w") as f:
        f.write("// Generated from config.json by src/generate_dataset.py. Do not edit by hand.\n")
        f.write("// The single source of truth for constants, shared with the Python core.\n")
        f.write("window.RV_CONFIG = ")
        json.dump(CONFIG_RAW, f, separators=(",", ":"))
        f.write(";\n")

    counts = dataset["meta"]["verdict_counts"]
    total_runs = sum(len(r["runs"]) for r in dataset["robots"])
    print(f"wrote {json_path}")
    print(f"wrote {js_path}")
    print(f"wrote {config_path}")
    print(f"fleet: {dataset['meta']['fleet_size']} arms, {dataset['meta']['days']} days, "
          f"{dataset['meta']['runs_per_day']} runs/day = {total_runs} test runs")
    print(f"per-run verdicts: {counts}")
    for robot in dataset["robots"]:
        for flag in robot["flags"]:
            print(
                f"  {robot['robot_id']} ({robot['profile']}): {flag['joint']} {flag['channel']} "
                f"= {flag['status']} (drift detected day {flag['detected_day']}, "
                f"cap crossed day {flag['cap_cross_day']})"
            )


if __name__ == "__main__":
    main()
