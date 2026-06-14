"""Wilson score confidence interval for a binomial success rate (pure stdlib).

Robot evals report a success rate over few trials. The naive normal interval
returns [1.0, 1.0] for 20 of 20, claiming certainty from twenty trials, and can
stray outside [0, 1]. Wilson stays in [0, 1], goes asymmetric near the edges, and
behaves at small n (20 of 20 lands near [0.84, 1.0]). It is the supporting piece
that ties robot uptime to how fast research can tell two policies apart; the
README explains that link.
"""

from dataclasses import dataclass
from math import sqrt

# z for common two-sided confidence levels.
Z_90 = 1.645
Z_95 = 1.96
Z_99 = 2.576


@dataclass(frozen=True)
class WilsonInterval:
    """A Wilson score interval plus the raw point estimate it came from."""

    low: float
    high: float
    center: float  # the Wilson center, pulled in from the point estimate toward 0.5
    point: float  # successes / n, the observed rate

    @property
    def width(self):
        return self.high - self.low


def wilson_interval(successes, n, z=Z_95):
    """Wilson score interval for `successes` out of `n` trials.

    z selects the confidence level (default 1.96 for 95 percent). The result is
    clamped to [0, 1] only at the very edges, where the formula's own bound
    already sits at 0 or 1, so the clamp never hides a real excursion; it just
    tidies floating point.
    """
    if n <= 0:
        raise ValueError("n must be a positive number of trials")
    if successes < 0 or successes > n:
        raise ValueError("successes must be between 0 and n inclusive")

    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half_width = (z * sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))) / denom

    low = max(0.0, center - half_width)
    high = min(1.0, center + half_width)
    return WilsonInterval(low=low, high=high, center=center, point=p)


def wilson_lower_bound(successes, n, z=Z_95):
    """Just the lower bound. Useful for conservative pass-or-fail ranking."""
    return wilson_interval(successes, n, z).low
