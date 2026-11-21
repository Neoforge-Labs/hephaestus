"""Date-to-release resolution (spec 10.3).

The clause exists so that a dated run evaluates the population that date would
have evaluated. The tests that matter most are the ones where a resolver that
peeked at a later release would still return something plausible: the date
before every release, and the date just before the newest.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from hephkit.errors import LAB_412, LAB_424
from hephkit.lab.data.releases import (
    AmbiguousReleaseError,
    NoEligibleReleaseError,
    Release,
    TemporalError,
    release_as_of,
)

JAN = Release(release="2026-01", published=date(2026, 1, 15))
FEB = Release(release="2026-02", published=date(2026, 2, 15))
MAR = Release(release="2026-03", published=date(2026, 3, 15))


def test_a_date_resolves_to_the_latest_release_published_on_or_before_it() -> None:
    assert release_as_of([JAN, FEB, MAR], date(2026, 3, 1)) == FEB
    assert release_as_of([JAN, FEB, MAR], date(2030, 1, 1)) == MAR


def test_a_release_published_after_the_date_is_unreachable() -> None:
    day_before_newest = date(2026, 3, 14)
    for order in ([JAN, FEB, MAR], [MAR, FEB, JAN], [FEB, MAR, JAN]):
        assert release_as_of(order, day_before_newest) == FEB


def test_a_date_equal_to_a_publication_date_resolves_to_that_release() -> None:
    assert release_as_of([JAN, FEB, MAR], date(2026, 2, 15)) == FEB


def test_a_date_before_every_release_is_refused() -> None:
    with pytest.raises(NoEligibleReleaseError) as excinfo:
        release_as_of([JAN, FEB, MAR], date(2026, 1, 14))
    assert excinfo.value.code == LAB_424


def test_an_empty_release_table_is_refused() -> None:
    with pytest.raises(NoEligibleReleaseError):
        release_as_of([], date(2026, 1, 1))


def test_releases_out_of_chronological_order_resolve_the_same() -> None:
    when = date(2026, 2, 20)
    assert release_as_of([MAR, JAN, FEB], when) == release_as_of([JAN, FEB, MAR], when) == FEB


A = Release(release="r9", published=date(2026, 2, 15))
B = Release(release="r10", published=date(2026, 2, 15))


def test_two_releases_sharing_the_latest_eligible_date_are_refused() -> None:
    for order in ([A, B], [B, A]):
        with pytest.raises(AmbiguousReleaseError) as excinfo:
            release_as_of(order, date(2026, 2, 20))
        assert excinfo.value.code == LAB_412
        message = str(excinfo.value)
        assert "2026-02-20" in message  # the date asked about
        assert "2026-02-15" in message  # the date they share
        assert "r9" in message and "r10" in message


def test_every_refusal_is_a_temporal_error_and_code_tells_them_apart() -> None:
    """The module's shape: one base to catch, `.code` to distinguish.

    The base carries the 412 its specific refusals carry, and the absence case
    is the subclass at 424 -- not the other way round, which would make the
    general `except` the narrow one (see `hephkit.lab`'s module docstring).
    """
    for refusal in (
        lambda: release_as_of([A, B], date(2026, 2, 20)),
        lambda: release_as_of([], date(2026, 2, 20)),
    ):
        with pytest.raises(TemporalError):
            refusal()
    assert issubclass(AmbiguousReleaseError, TemporalError)
    assert issubclass(NoEligibleReleaseError, TemporalError)
    assert TemporalError.code == LAB_412
    assert AmbiguousReleaseError.code == LAB_412
    assert NoEligibleReleaseError.code == LAB_424


def test_two_releases_with_the_same_label_on_the_same_date_are_still_refused() -> None:
    twin = Release(release="r9", published=date(2026, 2, 15))
    with pytest.raises(AmbiguousReleaseError, match="r9, r9"):
        release_as_of([A, twin], date(2026, 2, 15))


def test_a_collision_after_the_date_does_not_matter() -> None:
    assert release_as_of([A, B, JAN], date(2026, 2, 14)) == JAN


def test_a_collision_that_is_not_the_latest_eligible_does_not_matter() -> None:
    assert release_as_of([A, B, MAR], date(2026, 3, 20)) == MAR
    assert release_as_of([MAR, A, B], date(2026, 3, 20)) == MAR


def test_a_datetime_is_refused_with_a_type_error() -> None:
    with pytest.raises(TypeError):
        release_as_of([JAN], datetime(2026, 1, 15, 0, 0))


def test_a_release_is_frozen_and_refuses_unknown_members() -> None:
    with pytest.raises(ValidationError):
        JAN.release = "x"
    with pytest.raises(ValidationError):
        Release.model_validate({"release": "x", "published": "2026-01-01", "extra": 1})
