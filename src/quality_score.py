"""The per-run thermal gate: the data-integrity check before every test run.

It reads all seven joints, scores each one's headroom against that joint's own
datasheet limit (XM430-W350 to 80 C, XL430-W250 to 72 C), and takes the weakest
joint as the run's gate score. Score, verdict, and the per-joint breakdown become
the metadata stamped onto every episode the run records.

Scoring is percent of usable headroom: 100 up to (limit minus the healthy band),
then linear to 0 at the limit. A joint at 61 C on an 80 C limit scores 95. Only
the datasheet limits are sourced; the band and verdict offsets are illustrative
and live in config.json.
"""

from enum import Enum

from config import HEALTHY_BAND_C, QUARANTINE_OFFSET_C, SERVO_TEMPERATURE_LIMIT_C, WARN_OFFSET_C


class Verdict(Enum):
    """Three tiers. WARN maps onto PI's practice of tagging data for downweighting."""

    PASS = "PASS"              # collect
    WARN = "WARN"             # collect, but flag episodes for downweighting
    QUARANTINE = "QUARANTINE"  # do not collect, pull the robot

    @property
    def severity(self):
        return {"PASS": 0, "WARN": 1, "QUARANTINE": 2}[self.value]


def thermal_headroom_score(temperature_c, limit_c=SERVO_TEMPERATURE_LIMIT_C):
    """Percent of usable headroom to a joint's limit, in [0, 100]. Piecewise-linear
    because we have ground truth only at the healthy end and the limit; the danger
    near the limit is carried by the QUARANTINE step, not by bending the curve."""
    ceiling = limit_c - HEALTHY_BAND_C
    if temperature_c <= ceiling:
        return 100.0
    if temperature_c >= limit_c:
        return 0.0
    return 100.0 * (limit_c - temperature_c) / HEALTHY_BAND_C


def thermal_verdict(temperature_c, limit_c=SERVO_TEMPERATURE_LIMIT_C):
    """The operational decision for one joint, with a margin below its limit. The
    score reports headroom; this carries the action."""
    if temperature_c <= limit_c - WARN_OFFSET_C:
        return Verdict.PASS
    if temperature_c <= limit_c - QUARANTINE_OFFSET_C:
        return Verdict.WARN
    return Verdict.QUARANTINE


def worst_verdict(verdicts):
    """Weakest-link aggregation: the most severe verdict wins."""
    return max(verdicts, key=lambda v: v.severity)


class RunReport:
    """The gate's output for one run, with its derived values computed once."""

    def __init__(self, robot_id, run_id, timestamp, per_joint):
        self.robot_id, self.run_id, self.timestamp = robot_id, run_id, timestamp
        self.per_joint = per_joint  # {joint: {temp_c, limit_c, score, verdict}}
        self.weakest_joint = min(per_joint, key=lambda j: per_joint[j]["score"])
        self.gate_score = per_joint[self.weakest_joint]["score"]  # the weakest link
        self.verdict = worst_verdict([d["verdict"] for d in per_joint.values()])
        self.health_average = sum(d["score"] for d in per_joint.values()) / len(per_joint)

    def to_stamp(self):
        """The metadata attached to the run, so each episode inherits the health
        context of the robot that produced it (conditionable downstream)."""
        return {
            "robot_id": self.robot_id,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "quality_score": round(self.gate_score, 1),
            "verdict": self.verdict.value,
            "weakest_joint": self.weakest_joint,
            "health_average": round(self.health_average, 1),
            "joints": {
                j: {"temp_c": round(d["temp_c"], 1), "limit_c": d["limit_c"],
                    "score": round(d["score"], 1), "verdict": d["verdict"].value}
                for j, d in self.per_joint.items()
            },
            "note": (
                "Score is percent thermal headroom to each joint's datasheet limit "
                "(80 C XM430, 72 C XL430). The gate is the weakest joint. Verdict "
                "offsets are illustrative pending fleet validation."
            ),
        }


def evaluate_run(robot_id, run_id, timestamp, joint_temps_c, joint_limits_c):
    """Score one test run across all joints; the gate is the weakest joint."""
    if not joint_temps_c:
        raise ValueError("no joint temperatures provided")
    per_joint = {
        joint: {
            "temp_c": temp,
            "limit_c": joint_limits_c[joint],
            "score": thermal_headroom_score(temp, joint_limits_c[joint]),
            "verdict": thermal_verdict(temp, joint_limits_c[joint]),
        }
        for joint, temp in joint_temps_c.items()
    }
    return RunReport(robot_id, run_id, timestamp, per_joint)
