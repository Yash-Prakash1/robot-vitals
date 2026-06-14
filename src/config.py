"""Single source of truth for every tunable constant and the fleet config.

config.json (at the repo root) is the one place these values live. This module
reads it for the Python core, and src/generate_dataset.py emits the same file to
docs/config.js so the browser engine (docs/engine.js) reads identical values.
Change a number in config.json and it propagates to both, with no second place
to update. Only the formula bodies live in both languages.
"""

import json
import os
from datetime import date

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")
with open(_PATH) as _f:
    CONFIG = json.load(_f)

# gate: scoring and verdict offsets, applied relative to each joint's own limit
HEALTHY_BAND_C = CONFIG["gate"]["healthy_band_c"]          # healthy ceiling = limit - band
WARN_OFFSET_C = CONFIG["gate"]["warn_offset_c"]            # warn onset = limit - offset
QUARANTINE_OFFSET_C = CONFIG["gate"]["quarantine_offset_c"]  # quarantine onset = limit - offset

# servo temperature limits (the XM430 ceiling is the default / binding limit)
MODEL_TEMPERATURE_LIMIT_C = dict(CONFIG["servo_temperature_limit_c"])
SERVO_TEMPERATURE_LIMIT_C = MODEL_TEMPERATURE_LIMIT_C["XM430-W350"]

# cusum
BASELINE_DAYS = CONFIG["cusum"]["baseline_days"]
CUSUM_K_SIGMA = CONFIG["cusum"]["k_sigma"]
CUSUM_H_SIGMA = CONFIG["cusum"]["h_sigma"]

# maintenance (the effort cap score is derived from the two illustrative percents)
THERMAL_ACTION_CAP_SCORE = CONFIG["maintenance"]["thermal_action_cap_score"]
DRIFT_WATCH_SCORE = CONFIG["maintenance"]["drift_watch_score"]
EFFORT_ZERO_SCALE_PCT = CONFIG["maintenance"]["effort_zero_scale_pct"]
EFFORT_ACTION_CAP_PCT = CONFIG["maintenance"]["effort_action_cap_pct"]
EFFORT_ACTION_CAP_SCORE = 100.0 * (1.0 - EFFORT_ACTION_CAP_PCT / EFFORT_ZERO_SCALE_PCT)

# simulator
_sim = CONFIG["simulator"]
RUNS_PER_DAY = _sim["runs_per_day"]
INTRA_DAY_WARMUP_C = _sim["intra_day_warmup_c"]
RUN_NOISE_SIGMA_C = _sim["run_noise_sigma_c"]
CURRENT_NOISE_SIGMA_A = _sim["current_noise_sigma_a"]
CANONICAL_SEED = _sim["canonical_seed"]
JOINTS = tuple(_sim["joints"])
JOINT_NAMES = tuple(j["name"] for j in JOINTS)
JOINT_LIMIT_C = {j["name"]: MODEL_TEMPERATURE_LIMIT_C[j["model"]] for j in JOINTS}
JOINT_MODEL = {j["name"]: j["model"] for j in JOINTS}
BASE_TEMP_C = dict(_sim["base_temp_c"])
BASE_CURRENT_A = dict(_sim["base_current_a"])
FLEET = tuple(_sim["fleet"])

# dataset
START_DATE = date.fromisoformat(CONFIG["start_date"])
