"""Two-sided CUSUM drift detector (pure standard library).

CUSUM detects whether a signal has undergone a sustained one-directional shift
away from its healthy baseline, as opposed to ordinary noise. It detects; it does
not forecast (no "threshold crossed on date X"). Slack k and threshold h are in
units of the channel's own noise sigma, so they adapt to any channel. See the
README for why this beats a fixed limit. Tune k/h in config.json.
"""

from dataclasses import dataclass
from math import sqrt


def sample_std(values):
    """Unbiased sample standard deviation (divide by n minus 1)."""
    n = len(values)
    if n < 2:
        raise ValueError("need at least two values to estimate noise sigma")
    mean = sum(values) / n
    return sqrt(sum((x - mean) ** 2 for x in values) / (n - 1))


def baseline_stats(readings):
    """Return (mean, sample_std) of a healthy baseline window. The window must be
    drawn from healthy operation, before any drift, or it absorbs the shift."""
    return sum(readings) / len(readings), sample_std(readings)


@dataclass(frozen=True)
class CusumState:
    """Detector state after one reading. s_hi accumulates upward drift, s_lo
    downward. The upward arm is the one this project acts on."""

    s_hi: float
    s_lo: float
    alarm_high: bool
    alarm_low: bool

    @property
    def alarm(self):
        return self.alarm_high or self.alarm_low


class Cusum:
    """A two-sided CUSUM detector for one channel. k_sigma=0.5 tunes detection to
    a sustained ~1 sigma shift; h_sigma (4 to 5) sets the false-alarm rate."""

    def __init__(self, target, sigma, k_sigma=0.5, h_sigma=5.0):
        if sigma <= 0:
            raise ValueError("sigma must be positive")
        self.target, self.sigma = target, sigma
        self.k, self.h = k_sigma * sigma, h_sigma * sigma  # in raw signal units
        self.s_hi = self.s_lo = 0.0

    def update(self, x):
        # The max(0, ...) floor is the heart of CUSUM: zero-mean noise cannot
        # accumulate, so only persistent one-directional drift reaches the threshold.
        self.s_hi = max(0.0, self.s_hi + (x - self.target) - self.k)
        self.s_lo = max(0.0, self.s_lo + (self.target - x) - self.k)
        return CusumState(self.s_hi, self.s_lo, self.s_hi > self.h, self.s_lo > self.h)

    def reset(self):
        self.s_hi = self.s_lo = 0.0


def run(readings, target, sigma, k_sigma=0.5, h_sigma=5.0):
    """Run a fresh detector over a series and return the list of states."""
    detector = Cusum(target, sigma, k_sigma, h_sigma)
    return [detector.update(x) for x in readings]


def first_alarm(readings, target, sigma, k_sigma=0.5, h_sigma=5.0, direction="high"):
    """Index of the first reading at which the detector alarms, or None.
    direction is "high" (the project default), "low", or "either"."""
    if direction not in ("high", "low", "either"):
        raise ValueError("direction must be 'high', 'low', or 'either'")
    for i, st in enumerate(run(readings, target, sigma, k_sigma, h_sigma)):
        if getattr(st, "alarm" if direction == "either" else "alarm_" + direction):
            return i
    return None
