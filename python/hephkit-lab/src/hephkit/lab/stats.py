"""Effect sizes over two samples, test selection, and a refusal for every case they cannot serve.

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
and are never mutated.

Bootstrap intervals. :func:`bootstrap_ci` resamples one sample with
``scipy.stats.bootstrap`` (BCa, scipy's default) and returns an :class:`Interval`.
It is contract-tested, never vectored: a vector would have to take its numbers
from a seeded scipy run, which would make scipy's resampling order and RNG stream
the definition of our behaviour. The contract is that a nominal 95% interval
covers a known parameter at about the nominal rate, and that one seed gives one
interval. ``seed`` is required and reaches scipy as ``numpy.random.default_rng(seed)``,
passed explicitly; nothing reads global RNG state, so a recorded run replays.

A bootstrap of a constant sample returns a zero-width interval, and a zero-width
95% interval reads as certainty. So a sample of one observation, a constant
sample (all ties) and an empty or non-finite sample are :class:`StatsError`
(``HEPH-LAB-422``), as are a ``confidence`` outside the open interval (0, 1), a
``resamples`` below 1 and a negative ``seed``. All of that is checked *before*
scipy is imported, so a refusal works with no ``stats`` extra installed; only a
call that computes an interval needs it. :func:`aggregate_seeds` summarises one
number per seed (a run's metric under each seed) as a mean, a sample standard
deviation and a bootstrap interval of the mean, iterating the seeds in sorted
order so the summary cannot depend on how the mapping was built.

Test selection. :func:`choose_test` names the test a design calls for and
runs nothing: it is data in, data out, so it needs no extra. Its job is to
**refuse** when no test in the table is appropriate, because a selector that
always answers lets a researcher run a test whose assumptions the design does
not meet and report the p-value anyway. The table (``conformance/lab/selection.json``
pins every row):

* two interval groups, normal, unpaired: ``independent_t`` with equal variance,
  ``welch_t`` without; paired: ``paired_t`` (variance is not a condition of a
  paired design);
* two groups that are not normal, or ordinal: ``mann_whitney_u`` unpaired,
  ``wilcoxon_signed_rank`` paired (``normal=False`` decides before
  ``equal_variance`` is read, so there is never a Welch test on ranks);
* three or more unpaired groups: ``one_way_anova`` for interval, normal and
  equal variance, ``welch_anova`` for interval and normal with unequal
  variance, ``kruskal_wallis`` otherwise;
* nominal, unpaired: ``chi_square``, or ``fisher_exact`` when ``n_min`` (the
  smallest *expected* cell count) is below 5. A request carries no outcome
  categories, so it cannot say whether the table is 2x2; the ``fisher_exact``
  reason therefore says the test is of the full contingency table, the
  Freeman-Halton generalisation when it is larger than 2x2.

Refused: fewer than two groups, a paired nominal design, and a paired design
of three or more groups.

Three rulings go beyond the plan's table, which was wrong in all three places.
Interval, normal, unpaired groups of three or more with unequal variance get
``welch_anova`` rather than ``one_way_anova``: the caller stated the variance
assumption, and handing back a test that assumes the opposite would be the
failure this module exists to prevent; the table already draws the same line at
two groups (``independent_t`` against ``welch_t``).
Ordinal data with three or more groups joins the rank row (``kruskal_wallis``)
rather than being left without a test: the table said "interval" there, but
Kruskal-Wallis is the canonical rank test for ordinal data across independent
groups, so refusing it would be a false refusal. A paired design of three or
more groups is refused, not given repeated-measures ANOVA or Friedman: those
rest on assumptions such as sphericity, and a :class:`TestRequest` has no field
that can state one. That refusal is the request type being too small to carry
the choice, not a row someone forgot.

Maturity: experimental.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from statistics import fmean as mean

from pydantic import BaseModel, ConfigDict, Field

from hephkit.errors import LAB_422
from hephkit.lab._extras import require

__all__ = [
    "Interval",
    "Scale",
    "SeedSummary",
    "StatsError",
    "TestChoice",
    "TestRequest",
    "aggregate_seeds",
    "bootstrap_ci",
    "choose_test",
    "cliffs_delta",
    "cohens_d",
    "hedges_g",
    "mean",
]


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


class Scale(StrEnum):
    """The measurement scale of the outcome."""

    interval = "interval"
    ordinal = "ordinal"
    nominal = "nominal"


class TestRequest(BaseModel):
    """What the design says about its data: the only input :func:`choose_test` reads.

    ``groups`` and ``n_min`` cannot be negative, so a request that cannot exist
    fails here rather than reaching the table. ``n_min`` is the smallest
    *expected* cell count (used only for the nominal Fisher boundary). The model
    is strict: pass ``Scale.interval``, not the bare string ``"interval"``
    (JSON input, as the vectors hold it, is validated with
    ``model_validate_json``).
    """

    __test__ = False  # not a pytest class, despite the name

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    scale: Scale
    groups: int = Field(ge=0)
    paired: bool
    normal: bool
    equal_variance: bool
    n_min: int = Field(ge=0)


class TestChoice(BaseModel):
    """The test chosen and the properties of the design that decided it."""

    __test__ = False

    model_config = ConfigDict(frozen=True)

    test: str
    reason: str


def _rank_outcome(r: TestRequest) -> str:
    """The property that sends a design to a rank test, for a reason to quote."""
    return "ordinal outcome" if r.scale is Scale.ordinal else "interval outcome that is not normal"


def choose_test(request: TestRequest) -> TestChoice:
    """Name the test the design calls for, or raise :class:`StatsError` when the table has none."""
    r = request
    if r.groups == 0:
        raise StatsError("zero groups: there is nothing to compare")
    if r.groups == 1:
        raise StatsError("one group: a comparison needs at least two groups")
    if r.scale is Scale.nominal:
        if r.paired:
            raise StatsError(
                "a paired nominal design is not covered by the table "
                "(for two groups, McNemar's test)"
            )
        if r.n_min < 5:
            return TestChoice(
                test="fisher_exact",
                reason=f"nominal outcome with smallest expected cell count n_min {r.n_min} below 5, "
                "where chi-square's large-sample approximation does not hold; the exact test "
                "applies to the full contingency table, as the Freeman-Halton generalisation "
                "when it is larger than 2x2",
            )
        return TestChoice(
            test="chi_square",
            reason=f"nominal outcome with smallest expected cell count n_min {r.n_min} of at least 5",
        )
    if r.groups >= 3:
        if r.paired:
            raise StatsError(
                "a paired design of three or more groups is a repeated-measures design: the table "
                "covers none, and the choice depends on assumptions such as sphericity that this "
                "request cannot express (the request is too small to carry it, not a row missing)"
            )
        if r.scale is Scale.interval and r.normal:
            if r.equal_variance:
                return TestChoice(
                    test="one_way_anova",
                    reason=f"{r.groups} independent interval groups, normal, equal variance",
                )
            return TestChoice(
                test="welch_anova",
                reason=f"{r.groups} independent interval groups, normal, unequal variance",
            )
        why = _rank_outcome(r)
        return TestChoice(
            test="kruskal_wallis",
            reason=f"{r.groups} independent groups with an {why}, so a rank test",
        )
    if r.scale is Scale.ordinal or not r.normal:
        why = _rank_outcome(r)
        if r.paired:
            return TestChoice(
                test="wilcoxon_signed_rank",
                reason=f"two paired groups with an {why}, so a rank test on the differences",
            )
        return TestChoice(
            test="mann_whitney_u",
            reason=f"two independent groups with an {why}, so a rank test",
        )
    if r.paired:
        return TestChoice(
            test="paired_t",
            reason="two paired groups, interval outcome, normal",
        )
    if r.equal_variance:
        return TestChoice(
            test="independent_t",
            reason="two independent groups, interval outcome, normal, equal variance",
        )
    return TestChoice(
        test="welch_t",
        reason="two independent groups, interval outcome, normal, unequal variance",
    )


class Interval(BaseModel):
    """A confidence interval: ``low <= high``, at a ``confidence`` strictly between 0 and 1."""

    model_config = ConfigDict(frozen=True)

    low: float
    high: float
    confidence: float


def _confidence(confidence: float) -> float:
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        raise StatsError(f"confidence must be a number, not {confidence!r}")
    if not 0.0 < confidence < 1.0:  # False for nan, too
        raise StatsError(f"confidence must lie strictly between 0 and 1, not {confidence!r}")
    return float(confidence)


def _seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise StatsError(f"seed must be a non-negative integer, not {seed!r}")
    return seed


def bootstrap_ci(
    sample: Sequence[float],
    statistic: Callable[[Sequence[float]], float] = mean,
    *,
    confidence: float = 0.95,
    resamples: int = 10_000,
    seed: int,
) -> Interval:
    """A bootstrap (BCa) confidence interval of ``statistic`` over ``sample``.

    ``statistic`` receives each resample as a ``list`` of floats. Refuses
    (``StatsError``) a sample of fewer than two observations, a constant sample
    (a zero-width interval would read as certainty), an empty or non-finite
    sample, a ``confidence`` outside (0, 1), ``resamples`` below 1 and a negative
    ``seed``, all before scipy is imported. Two calls with the same arguments
    return the same interval.
    """
    xs = _sample(sample, "sample")
    level = _confidence(confidence)
    seed = _seed(seed)
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise StatsError(f"resamples must be an integer of at least 1, not {resamples!r}")
    if len(xs) < 2:
        raise StatsError("a bootstrap interval needs at least two observations")
    if min(xs) == max(xs):
        raise StatsError("the sample is constant: a bootstrap of it is a zero-width interval")
    numpy = require("numpy", extra="stats")
    stats = require("scipy.stats", extra="stats")

    def on_resample(resample: object) -> float:
        return float(statistic(list(map(float, resample))))  # type: ignore[call-overload]

    # A statistic whose bootstrap distribution is degenerate (a constant, `min`)
    # makes scipy warn and return nan; refuse that, as for a constant sample.
    with warnings.catch_warnings():
        warnings.simplefilter("error", stats.DegenerateDataWarning)
        try:
            result = stats.bootstrap(
                (numpy.asarray(xs),),
                on_resample,
                vectorized=False,
                n_resamples=resamples,
                confidence_level=level,
                method="BCa",
                random_state=numpy.random.default_rng(seed),
            )
        except stats.DegenerateDataWarning as exc:
            raise StatsError(f"the statistic has a degenerate bootstrap distribution: {exc}") from exc
    low = float(result.confidence_interval.low)
    high = float(result.confidence_interval.high)
    if not (math.isfinite(low) and math.isfinite(high)):
        raise StatsError("the bootstrap distribution of the statistic has no finite interval")
    return Interval(low=low, high=high, confidence=level)


class SeedSummary(BaseModel):
    """One metric across seeds: how many, their mean and sample standard deviation, and an interval of the mean."""

    model_config = ConfigDict(frozen=True)

    n: int
    mean: float
    sd: float
    interval: Interval


def aggregate_seeds(
    values: Mapping[int, float],
    *,
    confidence: float = 0.95,
    seed: int,
) -> SeedSummary:
    """Summarise one metric measured under several seeds (``values`` maps seed to metric).

    The values are taken in sorted seed order, so two mappings holding the same
    pairs give the same summary however they were built. Refuses (``StatsError``)
    fewer than two seeds, and every sample refusal of :func:`bootstrap_ci`,
    including identical values under every seed. ``seed`` drives the bootstrap
    only; it is unrelated to the keys of ``values``.
    """
    if not isinstance(values, Mapping):
        raise StatsError(f"values must map seed to metric, not {type(values).__name__}")
    ordered = [values[k] for k in sorted(values)]
    xs = _sample(ordered, "values")
    if len(xs) < 2:
        raise StatsError("a multi-seed summary needs at least two seeds")
    interval = bootstrap_ci(xs, confidence=confidence, seed=seed)
    centre = math.fsum(xs) / len(xs)
    sd = math.sqrt(_sum_of_squares(xs) / (len(xs) - 1))
    return SeedSummary(n=len(xs), mean=centre, sd=sd, interval=interval)
