"""Contract tests for ``hephkit.lab.stats`` effect sizes.

Every value here is worked by hand from the published definition in the
comment beside it; none was read off the code. No test is marked ``extras``:
effect sizes are arithmetic over sequences and run in the spine environment.
"""

from __future__ import annotations

import math

import pytest

from hephkit.errors import LAB_422
from pydantic import ValidationError

from hephkit.lab.stats import (
    Scale,
    StatsError,
    TestRequest,
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
    with pytest.raises(StatsError):
        cliffs_delta("abc", [1, 2])  # type: ignore[arg-type]


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
    with pytest.raises(StatsError, match=r"repeated-measures.*cannot express"):
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
    assert "paired" in choose_test(request(paired=True)).reason


def test_a_request_with_an_unknown_member_is_refused() -> None:
    with pytest.raises(ValidationError):
        TestRequest.model_validate(
            {
                "scale": "interval",
                "groups": 2,
                "paired": False,
                "normal": True,
                "equal_variance": True,
                "n_min": 3,
                "alpha": 0.05,
            }
        )


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
        choice.test = "welch_t"  # type: ignore[misc]
