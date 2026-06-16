"""The predictive-maintenance layer: longitudinal CUSUM, per joint, two channels.

End of day, the same registers the gate reads feed a CUSUM drift detector for
every joint, on a thermal channel (daily temperature) and an effort channel
(daily reference-motion current). Each channel reports a measured trend, a drift
status, and an action cap as a degradation magnitude, never a forecast date.

The channels are honestly tiered. Thermal is proven: its cap is anchored to the
joint's datasheet limit through the headroom score. Effort is a candidate: its
cap is a relative rise over the joint's own baseline, illustrative pending fleet
wear-rate data (the wear is certain physics; only its rate is unvalidated). All
constants live in config.json.
"""

from config import (
    BASELINE_DAYS,
    CUSUM_H_SIGMA,
    CUSUM_K_SIGMA,
    DRIFT_WATCH_SCORE,
    EFFORT_ACTION_CAP_PCT,
    EFFORT_ACTION_CAP_SCORE,
    EFFORT_ZERO_SCALE_PCT,
    JOINT_LIMIT_C,
    SERVO_TEMPERATURE_LIMIT_C,
    THERMAL_ACTION_CAP_SCORE,
)
from cusum import baseline_stats, first_alarm, sample_std
from quality_score import thermal_headroom_score


def effort_performance_score(current_a, baseline_a):
    """Map a reference current to 0..100 against the joint's own baseline: 100 at
    baseline, 0 at a EFFORT_ZERO_SCALE_PCT rise. Illustrative, no datasheet anchor."""
    if baseline_a <= 0:
        raise ValueError("baseline current must be positive")
    rise = (current_a - baseline_a) / baseline_a
    return max(0.0, min(100.0, 100.0 * (1.0 - rise / EFFORT_ZERO_SCALE_PCT)))


def pooled_sigma(groups):
    """One noise sigma estimated from many same-process groups: detrend each by
    its own mean and pool the residuals. Far tighter than a short per-channel
    window, which is what keeps healthy joints from false-alarming."""
    residuals = [x - sum(g) / len(g) for g in groups if len(g) >= 2 for x in g]
    return sample_std(residuals)


def _status_series(scores, cap_score, watch_score, alarm_day):
    """Per-day status. quarantine: degraded into the data-at-risk band (the joint
    is no longer working properly, pull it for maintenance). drifting: CUSUM
    detected a sustained shift AND the score dropped to the watch level (both
    significance and magnitude, so flat-but-noisy healthy joints do not flag). This
    is where 'quarantine' lives, a lasting trend judgement, not a single hot run."""
    out, quarantined = [], False
    for i, score in enumerate(scores):
        if score <= cap_score:
            quarantined = True            # latched: once the joint is pulled, it stays pulled,
        if quarantined:                   # so a noisy cool day cannot un-quarantine it
            out.append("quarantine")
        elif alarm_day is not None and i >= alarm_day and score <= watch_score:
            out.append("drifting")
        else:
            out.append("stable")
    return out


def analyze_channel(raw_series, score_fn, cap_score, channel, provenance,
                    baseline_days=BASELINE_DAYS, noise_sigma=None, watch_score=DRIFT_WATCH_SCORE):
    """One maintenance channel over a daily signal. score_fn(value, baseline_mean)
    returns a 0..100 score. noise_sigma, if given, is the pooled estimate. Reports
    the trend, the CUSUM detection day (past tense), the cap-cross day, and the
    status. No future date is ever projected."""
    if len(raw_series) <= baseline_days:
        raise ValueError("series shorter than the baseline window")
    mean, window_sigma = baseline_stats(raw_series[:baseline_days])
    sigma = max(window_sigma if noise_sigma is None else noise_sigma, 1e-9)
    alarm_day = first_alarm(raw_series, mean, sigma, CUSUM_K_SIGMA, CUSUM_H_SIGMA, "high")
    scores = [score_fn(x, mean) for x in raw_series]
    status_by_day = _status_series(scores, cap_score, watch_score, alarm_day)
    return {
        "channel": channel,
        "provenance": provenance,
        "raw": [round(x, 4) for x in raw_series],
        "performance_score": [round(s, 1) for s in scores],
        "baseline_mean": round(mean, 4),
        "baseline_sigma": round(sigma, 4),
        "cusum_detected_day": alarm_day,
        "cap_cross_day": next((i for i, s in enumerate(scores) if s <= cap_score), None),
        "action_cap_score": round(cap_score, 1),
        "status_by_day": status_by_day,
        "status": status_by_day[-1],
    }


def analyze_thermal(temp_series, baseline_days=BASELINE_DAYS, noise_sigma=None, limit_c=None):
    """Thermal channel: trend one joint's daily mean temperature, scored against
    that joint's datasheet limit (80 C XM430, 72 C XL430)."""
    limit = SERVO_TEMPERATURE_LIMIT_C if limit_c is None else limit_c
    return analyze_channel(
        temp_series, lambda x, _b: thermal_headroom_score(x, limit), THERMAL_ACTION_CAP_SCORE,
        "thermal", "proven: cap anchored to the servo datasheet limit",
        baseline_days=baseline_days, noise_sigma=noise_sigma,
    )


def analyze_effort(current_series, baseline_days=BASELINE_DAYS, noise_sigma=None):
    """Effort channel: trend one joint's daily reference current (labeled candidate)."""
    return analyze_channel(
        current_series, effort_performance_score, EFFORT_ACTION_CAP_SCORE,
        "effort", "candidate: occurrence certain, rate unvalidated for these gears",
        baseline_days=baseline_days, noise_sigma=noise_sigma,
    )


def _series(arm, key, joint, n):
    return [arm[key][d][joint] for d in range(n)]


def analyze_fleet(arms, joints, days, baseline_days=BASELINE_DAYS):
    """Run both channels for every joint of every arm. `arms` is the simulator
    output (per-day dicts daily_temp_c and daily_current_a keyed by joint). The
    noise sigma is pooled across all joints and arms over the baseline window,
    because noise is a sensor property, not a per-channel one.

    Returns {robot_id: {"joints": {joint: {"thermal", "effort"}}}}.
    """
    temp_sigma = pooled_sigma([_series(a, "daily_temp_c", j, baseline_days) for a in arms for j in joints])
    current_sigma = pooled_sigma([_series(a, "daily_current_a", j, baseline_days) for a in arms for j in joints])
    return {
        a["robot_id"]: {"joints": {
            j: {
                "thermal": analyze_thermal(_series(a, "daily_temp_c", j, days), baseline_days,
                                           noise_sigma=temp_sigma, limit_c=JOINT_LIMIT_C[j]),
                "effort": analyze_effort(_series(a, "daily_current_a", j, days), baseline_days,
                                         noise_sigma=current_sigma),
            }
            for j in joints
        }}
        for a in arms
    }
