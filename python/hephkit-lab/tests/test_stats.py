"""Contract tests for ``hephkit.lab.stats``.

Three things live here, in this order: the effect sizes, test selection, and the
bootstrap interval with the across-seeds summary.

Every value is worked by hand from the published definition in the comment
beside it; none was read off the code.

Most tests run in the spine environment, because effect sizes, `choose_test` and
every *refusal* of `bootstrap_ci` are arithmetic and validation with no extra
behind them. The tests that compute an interval, and the two that pass a polars
`Series` or a NumPy array, are marked ``extras``: they need SciPy or polars, and
`test-spine` deselects them.
"""

from __future__ import annotations

import json
import math
import statistics
from fractions import Fraction

import pytest
from pydantic import ValidationError

from hephkit.errors import LAB_422
from hephkit.lab.stats import (
    Interval,
    Scale,
    SeedSummary,
    StatsError,
    TestRequest,
    aggregate_seeds,
    bootstrap_ci,
    choose_test,
    cliffs_delta,
    cohens_d,
    hedges_g,
)


def test_the_error_carries_its_code() -> None:
    assert StatsError.code == LAB_422 == "HEPH-LAB-422"
    assert issubclass(StatsError, ValueError)


def test_cohens_d_of_identical_samples_is_zero() -> None:
    assert cohens_d([1, 2, 3], [1, 2, 3]) == 0.0


def test_cohens_d_divides_by_the_pooled_deviation() -> None:
    # means 2 and 4, both variances 1, pooled sd 1: d = -2.
    assert cohens_d([1, 2, 3], [3, 4, 5]) == -2.0
    # means 3 and 1, both variances 2: d = 2 / sqrt(2).
    assert cohens_d([2, 4], [0, 2]) == pytest.approx(math.sqrt(2), rel=1e-12)


def test_cohens_d_weights_each_variance_by_its_degrees_of_freedom() -> None:
    # var 1 (n=3) and var 2 (n=2): pooled variance (2*1 + 1*2)/3 = 4/3, d = -sqrt(3).
    # An unweighted mean of the variances would give -1.633.
    assert cohens_d([1, 2, 3], [3, 5]) == pytest.approx(-math.sqrt(3), rel=1e-12)


def test_hedges_g_is_d_times_the_small_sample_correction() -> None:
    # n = 6: J = 1 - 3/15 = 4/5, d = -2.
    assert hedges_g([1, 2, 3], [3, 4, 5]) == pytest.approx(-1.6, rel=1e-12)
    # n = 4: J = 4/7, d = sqrt(2).
    assert hedges_g([2, 4], [0, 2]) == pytest.approx(4 * math.sqrt(2) / 7, rel=1e-12)
    # n = 5: J = 8/11, d = -sqrt(3).
    assert hedges_g([1, 2, 3], [3, 5]) == pytest.approx(-8 * math.sqrt(3) / 11, rel=1e-12)


def test_hedges_g_is_smaller_in_magnitude_than_d() -> None:
    a, b = [1, 2, 3], [3, 4, 5]
    assert abs(hedges_g(a, b)) < abs(cohens_d(a, b))


def test_cliffs_delta_at_both_extremes_and_at_zero() -> None:
    assert cliffs_delta([4, 5, 6], [1, 2, 3]) == 1.0
    assert cliffs_delta([1, 2, 3], [4, 5, 6]) == -1.0
    assert cliffs_delta([1, 2, 3], [1, 2, 3]) == 0.0


def test_cliffs_delta_over_unequal_sizes() -> None:
    # pairs (1,2) less; (3,2) and (5,2) greater: (2 - 1)/3.
    assert cliffs_delta([1, 3, 5], [2]) == pytest.approx(1 / 3, rel=1e-12)


def test_cliffs_delta_counts_a_tie_in_the_denominator_only() -> None:
    # 6 pairs: 4 less, 0 greater, 2 ties.
    assert cliffs_delta([1, 2, 2], [2, 3]) == pytest.approx(-2 / 3, rel=1e-12)


def test_cliffs_delta_handles_all_ties() -> None:
    # Defined, not refused: it has no variance term to divide by.
    assert cliffs_delta([2, 2], [2, 2]) == 0.0
    assert cliffs_delta([7], [7]) == 0.0


def test_cliffs_delta_accepts_single_observations() -> None:
    assert cliffs_delta([1], [0]) == 1.0
    assert cliffs_delta([0], [1]) == -1.0


def test_a_zero_variance_pair_is_refused_rather_than_divided_by_zero() -> None:
    for statistic in (cohens_d, hedges_g):
        with pytest.raises(StatsError) as exc:
            statistic([2, 2, 2], [2, 2, 2])
        assert exc.value.code == "HEPH-LAB-422"


def test_one_constant_sample_against_one_varying_sample_is_a_finite_d() -> None:
    """The `and` in the zero-variance guard, pinned.

    A constant control group against a varying treatment is a design
    researchers actually run, and it has a pooled variance: for [1,2,3] the sum
    of squared deviations is 2 and for a constant sample it is 0, so the pooled
    variance is (0 + 2)/(3 + 3 - 2) = 0.5 and the pooled sd is sqrt(0.5).

    A mutation of that `and` to `or` would refuse all three of these.
    """
    # Means 2 and 2: the difference is 0, and 0/sqrt(0.5) is a finite 0.0.
    assert cohens_d([2, 2, 2], [1, 2, 3]) == 0.0
    # Means 3 and 2: d = 1/sqrt(0.5) = sqrt(2).
    assert cohens_d([3, 3, 3], [1, 2, 3]) == pytest.approx(math.sqrt(2), rel=1e-12)
    # The sign follows a - b, so the other way round is -sqrt(2).
    assert cohens_d([1, 2, 3], [3, 3, 3]) == pytest.approx(-math.sqrt(2), rel=1e-12)
    # n = 6, so J = 1 - 3/15 = 4/5.
    assert hedges_g([3, 3, 3], [1, 2, 3]) == pytest.approx(0.8 * math.sqrt(2), rel=1e-12)


def test_zero_variance_with_different_means_is_refused_not_infinite() -> None:
    for statistic in (cohens_d, hedges_g):
        with pytest.raises(StatsError):
            statistic([1, 1], [2, 2])


def test_a_pooled_deviation_that_underflows_is_refused_not_nan() -> None:
    # Neither sample is constant, but the squared deviations (~1e-400) underflow
    # to 0, so the pooled deviation is 0 and a quotient would be inf or nan.
    for statistic in (cohens_d, hedges_g):
        with pytest.raises(StatsError):
            statistic([0.0, 1e-200], [1e-200, 2e-200])


def test_a_single_observation_sample_is_refused() -> None:
    for statistic in (cohens_d, hedges_g):
        with pytest.raises(StatsError):
            statistic([5], [1, 2, 3])
        with pytest.raises(StatsError):
            statistic([1, 2, 3], [5])
        with pytest.raises(StatsError):
            statistic([5], [6])


def test_an_empty_sample_is_refused() -> None:
    for statistic in (cohens_d, hedges_g, cliffs_delta):
        with pytest.raises(StatsError):
            statistic([], [1, 2, 3])
        with pytest.raises(StatsError):
            statistic([1, 2, 3], [])


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_value_is_refused(bad: float) -> None:
    for statistic in (cohens_d, hedges_g, cliffs_delta):
        with pytest.raises(StatsError):
            statistic([1, 2, bad], [1, 2, 3])
        with pytest.raises(StatsError):
            statistic([1, 2, 3], [1, 2, bad])


def test_a_bool_or_non_number_is_refused() -> None:
    with pytest.raises(StatsError):
        cohens_d([True, False], [1, 2])
    with pytest.raises(StatsError):
        cliffs_delta(["a", "b"], [1, 2])  # type: ignore[list-item]


def test_a_string_is_not_a_sample() -> None:
    # Iterable, but iterating it would read characters as observations.
    with pytest.raises(StatsError):
        cliffs_delta("abc", [1, 2])  # type: ignore[arg-type]
    with pytest.raises(StatsError):
        cliffs_delta(b"abc", [1, 2])  # type: ignore[arg-type]


def test_any_other_iterable_is_a_sample() -> None:
    """Wider than `Sequence`, which is what refused a frame column.

    No extra needed for these three: the gate is about the container, and a
    `set` is unordered but every statistic here is order-independent.
    """
    assert cohens_d((1, 2, 3), (3, 4, 5)) == -2.0
    assert cohens_d(iter([1, 2, 3]), iter([3, 4, 5])) == -2.0
    assert hedges_g(iter([1, 2, 3]), iter([3, 4, 5])) == pytest.approx(-1.6, rel=1e-12)
    assert cliffs_delta(iter([4, 5, 6]), iter([1, 2, 3])) == 1.0


def test_a_fraction_is_a_real_number() -> None:
    # `numbers.Real`, not `int | float`: this is what also admits `numpy.int64`.
    assert cohens_d([Fraction(1), Fraction(2), Fraction(3)], [3, 4, 5]) == -2.0


def test_inputs_are_not_mutated_and_order_does_not_matter() -> None:
    a, b = [3, 1, 2], [5, 3, 4]
    before = (list(a), list(b))
    assert cohens_d(a, b) == cohens_d([1, 2, 3], [3, 4, 5])
    assert cliffs_delta(a, b) == cliffs_delta([1, 2, 3], [3, 4, 5])
    assert (a, b) == before


def test_cliffs_delta_is_antisymmetric() -> None:
    a, b = [1, 4, 4, 9], [2, 4, 7]
    assert cliffs_delta(a, b) == -cliffs_delta(b, a)


def request(**kw: object) -> TestRequest:
    base: dict[str, object] = {
        "scale": Scale.interval,
        "groups": 2,
        "paired": False,
        "normal": True,
        "equal_variance": True,
        "n_min": 30,
    }
    return TestRequest.model_validate(base | kw)


def test_an_inappropriate_test_is_refused_rather_than_approximated() -> None:
    for kw in (
        {"groups": 1},
        {"groups": 0},
        {"scale": Scale.nominal, "paired": True},
        {"groups": 3, "paired": True},
        {"groups": 5, "paired": True, "normal": False},
        {"scale": Scale.ordinal, "groups": 3, "paired": True},
        {"scale": Scale.interval, "groups": 5, "paired": True, "normal": False},
    ):
        with pytest.raises(StatsError) as exc:
            choose_test(request(**kw))
        assert exc.value.code == "HEPH-LAB-422", kw


def test_the_refusal_says_what_was_wrong_with_the_request() -> None:
    with pytest.raises(StatsError, match="one group"):
        choose_test(request(groups=1))
    with pytest.raises(StatsError, match="zero groups"):
        choose_test(request(groups=0))
    with pytest.raises(StatsError, match="paired nominal"):
        choose_test(request(scale=Scale.nominal, paired=True))
    with pytest.raises(StatsError, match="sphericity"):
        choose_test(request(groups=3, paired=True))


def test_a_small_nominal_cell_count_chooses_fisher_over_chi_square() -> None:
    assert choose_test(request(scale=Scale.nominal, n_min=4)).test == "fisher_exact"
    assert choose_test(request(scale=Scale.nominal, n_min=0)).test == "fisher_exact"
    assert choose_test(request(scale=Scale.nominal, n_min=5)).test == "chi_square"


def test_the_reason_names_the_rule_that_decided() -> None:
    assert "unequal variance" in choose_test(request(equal_variance=False)).reason
    assert "n_min 4" in choose_test(request(scale=Scale.nominal, n_min=4)).reason
    assert "not normal" in choose_test(request(normal=False)).reason
    assert "ordinal" in choose_test(request(scale=Scale.ordinal)).reason
    assert choose_test(request(paired=True)).reason == "two paired groups, interval outcome, normal"
    assert "unequal variance" in choose_test(request(groups=3, equal_variance=False)).reason
    assert "Freeman-Halton" in choose_test(request(scale=Scale.nominal, groups=3, n_min=2)).reason
    assert "expected cell count" in choose_test(request(scale=Scale.nominal)).reason


def test_a_request_with_an_unknown_member_is_refused() -> None:
    """`extra="forbid"`, pinned by the stray member and nothing else.

    Through `model_validate_json`, the mode the vectors use: a strict model
    takes its enum from a JSON string there, so `scale` is accepted and `alpha`
    is the only thing left that can fail. Passing the bare string to
    `model_validate` instead would be refused for the enum on its own, and the
    test would pass with `extra="forbid"` removed.
    """
    payload = {
        "scale": "interval",
        "groups": 2,
        "paired": False,
        "normal": True,
        "equal_variance": True,
        "n_min": 3,
    }
    assert TestRequest.model_validate_json(json.dumps(payload)).groups == 2
    with pytest.raises(ValidationError, match="alpha"):
        TestRequest.model_validate_json(json.dumps({**payload, "alpha": 0.05}))


def test_a_request_that_cannot_exist_is_refused_by_construction() -> None:
    with pytest.raises(ValidationError):
        request(groups=-1)
    with pytest.raises(ValidationError):
        request(n_min=-1)
    with pytest.raises(ValidationError):
        request(groups="2")


def test_normal_false_overrides_equal_variance() -> None:
    assert choose_test(request(normal=False, equal_variance=False)).test == "mann_whitney_u"


def test_three_ordinal_groups_take_the_rank_test() -> None:
    assert choose_test(request(scale=Scale.ordinal, groups=3)).test == "kruskal_wallis"


def test_the_choice_is_frozen() -> None:
    choice = choose_test(request())
    with pytest.raises(ValidationError):
        choice.test = "welch_t"  # mypy gates src only; this line is not type-checked


def test_three_normal_groups_with_unequal_variance_take_welch_anova() -> None:
    assert choose_test(request(groups=3, equal_variance=False)).test == "welch_anova"
    assert choose_test(request(groups=3, equal_variance=True)).test == "one_way_anova"
    # Non-normal decides before variance is read, as at two groups.
    assert choose_test(request(groups=3, normal=False, equal_variance=False)).test == "kruskal_wallis"


def test_nominal_groups_of_three_take_the_same_rule_as_two() -> None:
    assert choose_test(request(scale=Scale.nominal, groups=3, n_min=5)).test == "chi_square"
    assert choose_test(request(scale=Scale.nominal, groups=3, n_min=4)).test == "fisher_exact"


def test_the_strict_model_wants_the_enum_member_not_the_string() -> None:
    with pytest.raises(ValidationError):
        TestRequest.model_validate(
            {
                "scale": "interval",
                "groups": 2,
                "paired": False,
                "normal": True,
                "equal_variance": True,
                "n_min": 9,
            }
        )


# --- bootstrap intervals and seed aggregation -------------------------------
#
# Contract-tested, never vectored (design 9.3): the expected numbers of a seeded
# scipy run would make scipy's resampling order and RNG stream the definition.
# The refusal tests below are unmarked on purpose: the sample is validated before
# scipy is imported, so they run in the spine environment with no `stats` extra.


def test_a_zero_variance_sample_is_refused_rather_than_given_a_zero_width_interval() -> None:
    with pytest.raises(StatsError, match="constant"):
        bootstrap_ci([3.0, 3.0, 3.0, 3.0], seed=1)


def test_all_ties_of_integers_are_refused_too() -> None:
    with pytest.raises(StatsError, match="constant"):
        bootstrap_ci([7, 7], seed=1)


def test_a_single_observation_sample_is_refused() -> None:
    with pytest.raises(StatsError, match="at least two"):
        bootstrap_ci([4.2], seed=1)


@pytest.mark.parametrize("bad", [[], [1.0, math.nan, 3.0], [1.0, math.inf], [True, False], "12", [1, "2"]])
def test_an_unusable_sample_is_refused(bad: object) -> None:
    with pytest.raises(StatsError):
        bootstrap_ci(bad, seed=1)  # type: ignore[arg-type]


@pytest.mark.parametrize("confidence", [0.0, 1.0, -0.5, 1.5, math.nan, math.inf, True, "0.95"])
def test_a_confidence_outside_the_open_unit_interval_is_refused(confidence: object) -> None:
    with pytest.raises(StatsError, match="confidence"):
        bootstrap_ci([1.0, 2.0, 4.0], confidence=confidence, seed=1)  # type: ignore[arg-type]


@pytest.mark.parametrize("resamples", [0, -3, 2.5, True])
def test_fewer_than_one_resample_is_refused(resamples: object) -> None:
    with pytest.raises(StatsError, match="resamples"):
        bootstrap_ci([1.0, 2.0, 4.0], resamples=resamples, seed=1)  # type: ignore[arg-type]


@pytest.mark.parametrize("seed", [-1, 1.5, True, "1"])
def test_a_seed_that_is_not_a_non_negative_integer_is_refused(seed: object) -> None:
    with pytest.raises(StatsError, match="seed"):
        bootstrap_ci([1.0, 2.0, 4.0], seed=seed)  # type: ignore[arg-type]


def test_aggregate_seeds_refuses_a_single_seed() -> None:
    with pytest.raises(StatsError, match="at least two seeds"):
        aggregate_seeds({0: 0.9}, seed=1)


def test_aggregate_seeds_refuses_identical_values_under_every_seed() -> None:
    with pytest.raises(StatsError, match="constant"):
        aggregate_seeds({0: 0.9, 1: 0.9, 2: 0.9}, seed=1)


def test_aggregate_seeds_refuses_no_seeds_and_a_non_mapping() -> None:
    with pytest.raises(StatsError):
        aggregate_seeds({}, seed=1)
    with pytest.raises(StatsError, match="map seed to metric"):
        aggregate_seeds([0.1, 0.2], seed=1)  # type: ignore[arg-type]


def test_an_interval_enforces_what_its_docstring_promises() -> None:
    """`low <= high` and `0 < confidence < 1`, both checked.

    It is an exported model a caller constructs, so an interval built the wrong
    way round would read as a valid one and bracket nothing.
    """
    assert Interval(low=1.0, high=1.0, confidence=0.5).low == 1.0  # a point is not inverted
    with pytest.raises(ValidationError, match="low <= high"):
        Interval(low=2.0, high=1.0, confidence=0.95)
    for bad in (0.0, 1.0, -0.5, 1.5):
        with pytest.raises(ValidationError):
            Interval(low=1.0, high=2.0, confidence=bad)


def test_an_interval_and_a_summary_are_frozen() -> None:
    interval = Interval(low=1.0, high=2.0, confidence=0.9)
    with pytest.raises(ValidationError):
        interval.low = 0.0  # mypy gates src only; this line is not type-checked
    summary = SeedSummary(n=2, mean=1.5, sd=0.5, interval=interval)
    with pytest.raises(ValidationError):
        summary.n = 3  # mypy gates src only; this line is not type-checked


@pytest.mark.extras
def test_a_polars_series_and_a_numpy_array_are_samples() -> None:
    """The composition of the two modules this wave shipped, pinned.

    `frame["a"]` is a polars `Series` and `.to_numpy()` is an `ndarray`;
    neither is a `collections.abc.Sequence`, so both were refused, and so was
    `list()` of an integer NumPy array, because `np.int64` is not an `int`.
    Only `.to_list()` worked, which made the obvious call the wrong one.
    """
    import numpy
    import polars as pl

    frame = pl.DataFrame({"a": [0.71, 0.74, 0.69, 0.73, 0.70], "b": [0.78, 0.81, 0.76, 0.80, 0.79]})
    expected = cohens_d(frame["a"].to_list(), frame["b"].to_list())
    assert cohens_d(frame["a"], frame["b"]) == expected
    assert cohens_d(frame["a"].to_numpy(), frame["b"].to_numpy()) == expected
    assert hedges_g(frame["a"], frame["b"]) == hedges_g(
        frame["a"].to_list(), frame["b"].to_list()
    )
    assert cliffs_delta(frame["a"], frame["b"]) == -1.0
    # An integer NumPy array, as an array and as a list of its np.int64 values.
    counts = numpy.array([3, 5, 4, 6])
    assert cohens_d(counts, [1, 2, 3, 2]) == cohens_d(counts.tolist(), [1, 2, 3, 2])
    assert cohens_d(list(counts), [1, 2, 3, 2]) == cohens_d(counts.tolist(), [1, 2, 3, 2])
    # And through the bootstrap, which materialises the sample for SciPy.
    series = bootstrap_ci(frame["a"], resamples=400, seed=3)
    assert series == bootstrap_ci(frame["a"].to_list(), resamples=400, seed=3)
    assert series == bootstrap_ci(frame["a"].to_numpy(), resamples=400, seed=3)
    assert series == bootstrap_ci(numpy.asarray(frame["a"].to_list()), resamples=400, seed=3)


@pytest.mark.extras
def test_the_widened_gate_still_refuses_a_bool_and_a_nan_from_a_library() -> None:
    """The two refusals that are judgements, not type narrowness.

    `numpy.bool_` is not a Python `bool` and is not a `numbers.Real`, so a
    boolean array is refused as "not a real number" rather than read as 0 and 1;
    a NumPy `nan` is refused as not finite, as a Python one is.
    """
    import numpy
    import polars as pl

    with pytest.raises(StatsError, match="not a real number"):
        cohens_d(numpy.array([True, False, True]), [1, 2, 3])
    with pytest.raises(StatsError, match="not a real number"):
        cohens_d(pl.Series([True, False, True]), [1, 2, 3])
    with pytest.raises(StatsError, match="not finite"):
        cohens_d(numpy.array([1.0, numpy.nan, 3.0]), [1, 2, 3])
    with pytest.raises(StatsError, match="not finite"):
        bootstrap_ci(numpy.array([1.0, numpy.inf, 3.0]), seed=1)


@pytest.mark.extras
def test_two_runs_at_one_seed_give_the_same_interval() -> None:
    sample = [2.1, 3.4, 1.9, 5.6, 4.0, 3.3, 2.8, 4.7]
    first = bootstrap_ci(sample, resamples=500, seed=42)
    assert bootstrap_ci(sample, resamples=500, seed=42) == first
    # The seed is what decides: another seed resamples differently.
    assert bootstrap_ci(sample, resamples=500, seed=43) != first


@pytest.mark.extras
def test_the_global_random_state_does_not_reach_the_interval() -> None:
    import random

    import numpy

    sample = [2.1, 3.4, 1.9, 5.6, 4.0, 3.3, 2.8, 4.7]
    random.seed(1)
    numpy.random.seed(1)
    first = bootstrap_ci(sample, resamples=300, seed=7)
    random.seed(999)
    numpy.random.seed(999)
    assert bootstrap_ci(sample, resamples=300, seed=7) == first


@pytest.mark.extras
def test_an_interval_brackets_the_statistic_and_reports_its_confidence() -> None:
    sample = [2.1, 3.4, 1.9, 5.6, 4.0, 3.3, 2.8, 4.7]
    interval = bootstrap_ci(sample, resamples=500, confidence=0.9, seed=5)
    assert interval.confidence == 0.9
    assert interval.low < math.fsum(sample) / len(sample) < interval.high


@pytest.mark.extras
def test_a_wider_confidence_gives_a_wider_interval() -> None:
    sample = [2.1, 3.4, 1.9, 5.6, 4.0, 3.3, 2.8, 4.7]
    narrow = bootstrap_ci(sample, resamples=1000, confidence=0.5, seed=5)
    wide = bootstrap_ci(sample, resamples=1000, confidence=0.99, seed=5)
    assert wide.high - wide.low > narrow.high - narrow.low


@pytest.mark.extras
def test_the_statistic_is_the_one_asked_for() -> None:
    sample = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 100.0]
    ci = bootstrap_ci(sample, statistics.median, resamples=500, seed=3)
    assert ci.low < statistics.median(sample) < ci.high
    # The mean of this sample is 14.5, far above anything the median interval reaches.
    assert ci.high < 14.5


@pytest.mark.extras
def test_a_nominal_95_interval_covers_a_known_parameter_about_95_percent_of_the_time() -> None:
    import numpy

    # Normal(10, 2), n = 100, true mean 10, BCa. The tolerance is derived, not chosen:
    # the measured coverage of `replicates` independent intervals has Monte Carlo
    # standard error sqrt(p (1 - p) / replicates) at p = 0.95, which is about 0.0109
    # at 400 replicates; three of them is 0.0327, so the band is 0.95 +/- 0.0327
    # and a correct interval falls outside it about 0.3% of the time. Changing
    # `replicates` moves the band with it. An interval that is too narrow or too
    # wide by any meaningful amount lands many SE outside (the sample's min and max
    # would cover ~100%, a point estimate 0%).
    true_mean, sd, n = 10.0, 2.0, 100
    replicates, resamples = 400, 300
    rng = numpy.random.default_rng(20261121)
    nominal = 0.95
    tolerance = 3 * math.sqrt(nominal * (1 - nominal) / replicates)
    covered = 0
    for i in range(replicates):
        draw = rng.normal(true_mean, sd, size=n).tolist()
        ci = bootstrap_ci(draw, resamples=resamples, confidence=0.95, seed=i)
        covered += ci.low <= true_mean <= ci.high
    coverage = covered / replicates
    assert abs(coverage - nominal) <= tolerance, (coverage, tolerance)


@pytest.mark.extras
def test_aggregate_seeds_reports_the_seed_count_it_was_given() -> None:
    summary = aggregate_seeds({0: 0.80, 1: 0.84, 2: 0.82, 3: 0.86, 4: 0.78}, seed=11)
    assert summary.n == 5
    assert summary.mean == pytest.approx(0.82, rel=1e-12)
    # sample variance (divisor n - 1): deviations -.02 .02 0 .04 -.04 -> 0.004 / 4.
    assert summary.sd == pytest.approx(math.sqrt(0.001), rel=1e-9)
    assert summary.interval.low < summary.mean < summary.interval.high
    assert summary.interval.confidence == 0.95


@pytest.mark.extras
def test_aggregate_seeds_does_not_depend_on_the_mapping_order() -> None:
    pairs = [(0, 0.80), (1, 0.84), (2, 0.82), (3, 0.86), (4, 0.78)]
    forward = dict(pairs)
    backward = dict(reversed(pairs))
    assert list(forward) != list(backward)
    assert aggregate_seeds(forward, seed=11) == aggregate_seeds(backward, seed=11)


@pytest.mark.extras
def test_a_statistic_with_a_degenerate_bootstrap_distribution_is_refused() -> None:
    with pytest.raises(StatsError, match="degenerate bootstrap distribution"):
        bootstrap_ci([1.0, 2.0, 4.0, 8.0], lambda _: math.nan, resamples=50, seed=1)
