"""Effect sizes over two samples, and a refusal for every sample they cannot describe.

An effect size says how large a difference is, which a p-value does not. This
module holds the three the kit reports: Cohen's *d*, Hedges' *g* and Cliff's
*delta*. They are arithmetic over sequences, so nothing here needs an extra and
nothing here imports ``numpy`` or ``scipy``.

Definitions (the vectors in ``conformance/lab/effects.json`` are worked from
these by hand):

* Cohen's *d* = ``(mean(a) - mean(b)) / s_pooled``, where
  ``s_pooled = sqrt(((n_a - 1) var_a + (n_b - 1) var_b) / (n_a + n_b - 2))`` and
  the variances are sample variances (divisor ``n - 1``). The sign follows
  ``a - b``.
* Hedges' *g* = ``d * (1 - 3 / (4 (n_a + n_b) - 9))``, the small-sample correction
  of *d*; it is computed from :func:`cohens_d`, not alongside it.
* Cliff's *delta* = ``(#(x > y) - #(x < y)) / (n_a n_b)`` over every pair
  ``(x, y)`` with ``x`` from ``a`` and ``y`` from ``b``. A tie (``x == y``) is
  neither greater nor less: it counts in the denominator only, so ties pull the
  value toward 0.

Which samples are refused, and why a number would be worse: Cohen's *d* divides
by a pooled standard deviation, and a naive implementation turns the cases that
have none into a plausible figure nobody can challenge. A sample of one
observation has no sample variance; two constant samples have a pooled deviation
of 0, so *d* is ``0/0`` when the means agree and an infinity when they do not.
Each is :class:`StatsError` (``HEPH-LAB-422``), as are an empty sample, a value
that is not a finite real number (``nan``, ``inf``, a ``bool``, a string) and a
sample that is itself a ``str`` or ``bytes``. Cliff's *delta* has no variance
term, so a single observation or a fully tied pair is a defined value (0 for
all ties), not a refusal; it still refuses an empty sample, which would divide
by zero.

Limits: the arithmetic is double precision, with means and sums of squares
accumulated by ``math.fsum``. A constant sample is recognised by its minimum
equalling its maximum, which is exact, rather than by a variance that rounding
could leave a hair above 0. Samples are not copied beyond a read of each value
and are never mutated. Test selection and bootstrap intervals are not here.

Maturity: experimental.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from hephkit.errors import LAB_422

__all__ = ["StatsError", "cliffs_delta", "cohens_d", "hedges_g"]


class StatsError(ValueError):
    """A sample cannot support the statistic asked of it (``HEPH-LAB-422``)."""

    code = LAB_422


def _sample(values: Sequence[float], name: str) -> list[float]:
    """Validate one sample and return it as floats: a sequence of finite real numbers."""
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise StatsError(f"sample {name!r} must be a sequence of numbers, not {type(values).__name__}")
    if not values:
        raise StatsError(f"sample {name!r} is empty")
    out: list[float] = []
    for i, v in enumerate(values):
        # bool is an int subclass, and True as an observation is a mistake, not a 1.
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise StatsError(f"sample {name!r}[{i}] is not a real number: {v!r}")
        x = float(v)
        if not math.isfinite(x):
            raise StatsError(f"sample {name!r}[{i}] is not finite: {v!r}")
        out.append(x)
    return out


def _sum_of_squares(xs: list[float]) -> float:
    """Sum of squared deviations from the mean, accumulated exactly-rounded."""
    mean = math.fsum(xs) / len(xs)
    return math.fsum((x - mean) ** 2 for x in xs)


def cohens_d(a: Sequence[float], b: Sequence[float]) -> float:
    """Cohen's *d* for ``a`` against ``b``: the mean difference over the pooled standard deviation.

    Refuses (``StatsError``) an empty sample, a sample of fewer than two
    observations, non-finite input, and two constant samples (zero pooled
    deviation) rather than returning ``0.0``, ``inf`` or ``nan``.
    """
    xa, xb = _sample(a, "a"), _sample(b, "b")
    if len(xa) < 2 or len(xb) < 2:
        raise StatsError("Cohen's d needs at least two observations in each sample")
    if min(xa) == max(xa) and min(xb) == max(xb):
        raise StatsError("both samples are constant: the pooled standard deviation is 0")
    df = len(xa) + len(xb) - 2
    pooled_variance = (_sum_of_squares(xa) + _sum_of_squares(xb)) / df
    difference = math.fsum(xa) / len(xa) - math.fsum(xb) / len(xb)
    pooled = math.sqrt(pooled_variance)
    # A pooled deviation that underflows to 0, or a quotient that overflows,
    # would hand back inf or nan; say so rather than return it.
    d = difference / pooled if pooled > 0.0 else math.nan
    if not math.isfinite(d):
        raise StatsError("the standardised difference is not a finite number")
    return d


def hedges_g(a: Sequence[float], b: Sequence[float]) -> float:
    """Hedges' *g*: Cohen's *d* times ``1 - 3 / (4 (n_a + n_b) - 9)``.

    Takes every refusal of :func:`cohens_d`, which it calls.
    """
    d = cohens_d(a, b)
    n = len(a) + len(b)
    return d * (1.0 - 3.0 / (4.0 * n - 9.0))


def cliffs_delta(a: Sequence[float], b: Sequence[float]) -> float:
    """Cliff's *delta*: ``(#(x > y) - #(x < y)) / (n_a n_b)`` over all pairs, ties in neither count.

    Refuses an empty sample and non-finite input. Unlike Cohen's *d* it needs
    no variance, so one observation per sample, or all ties (0.0), is defined.
    """
    xa, xb = _sample(a, "a"), _sample(b, "b")
    greater = less = 0
    for x in xa:
        for y in xb:
            if x > y:
                greater += 1
            elif x < y:
                less += 1
    return (greater - less) / (len(xa) * len(xb))
