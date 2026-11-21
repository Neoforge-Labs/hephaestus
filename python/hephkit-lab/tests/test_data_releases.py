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


@pytest.mark.parametrize(
    "bad",
    [0, 1764000000, 1.5, True, None, [], {}],
    ids=["epoch", "unix-seconds", "float", "bool", "null", "array", "object"],
)
def test_a_published_whose_type_is_not_a_date_is_refused(bad: object) -> None:
    """10.4: a member whose type is not section 10's is invalid, not coerced.

    Read off the clause: 10.3 makes `published` an RFC 3339 `full-date`, so a
    number is not one. This is the refusal that matters most in section 10,
    because `published` is the only thing 10.3 orders releases by -- see the
    test below for what accepting it would do.
    """
    with pytest.raises(TemporalError) as excinfo:
        Release.model_validate({"release": "r", "published": bad})
    assert excinfo.value.code == LAB_412


def test_a_numeric_published_cannot_resolve_every_date_against_1970() -> None:
    """The consequence, stated as a test rather than left to the reader.

    Lax coercion read `published=0` as 1970-01-01. A table built that way is
    eligible for every date a run could ask about, so `release_as_of` returned
    a release -- hindsight in the sampling frame, with no refusal and no
    warning. The refusal has to happen where the table is built, because by the
    time the resolver sees a `date` the information that it was a number is gone.
    """
    with pytest.raises(TemporalError):
        release_as_of(
            [Release.model_validate({"release": "epoch", "published": 0})], date(2026, 6, 1)
        )


def test_a_published_that_is_a_datetime_is_refused_not_truncated() -> None:
    with pytest.raises(TemporalError, match="full-date"):
        Release(release="r", published=datetime(2026, 1, 15, 0, 0))


def test_a_string_that_is_not_a_date_is_pydantics_refusal_not_this_modules() -> None:
    """Where the coded refusal stops, said out loud so it is not rediscovered.

    The type gate above is about the *type*: a string is the type 10.3 gives, so
    a string that is not a well-formed date passes the gate and pydantic's own
    date parser refuses it -- a `ValidationError` carrying no `.code`, because
    this module has no parse function to translate one into a `TemporalError`
    the way `lab.data.manifest.parse_manifest` does. Still a refusal, and never
    a wrong date; just not a coded one.
    """
    with pytest.raises(ValidationError):
        Release.model_validate({"release": "r", "published": "not-a-date"})


def test_the_two_forms_a_published_may_take_are_both_accepted() -> None:
    """The refusal must not have closed the door on the string 10.3 asks for."""
    assert Release.model_validate({"release": "2026-01", "published": "2026-01-15"}) == JAN


def test_a_release_is_frozen_and_refuses_unknown_members() -> None:
    with pytest.raises(ValidationError):
        JAN.release = "x"
    with pytest.raises(ValidationError):
        Release.model_validate({"release": "x", "published": "2026-01-01", "extra": 1})
