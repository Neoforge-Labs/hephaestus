"""Date-to-release resolution (spec 10.3).

A dated run must evaluate the population that date would have evaluated, so a
date resolves to the latest release published on or before it and never to one
published after. :func:`release_as_of` refuses when no release qualifies: a
date that precedes every release is not answered with the earliest release,
because that release is itself from the future of the date.

The resolver filters first and chooses second, so a release published after
the date is never a candidate and no ordering of the input can make it one.
Both sides are RFC 3339 ``full-date``s compared as calendar dates; a
``datetime`` is not a date and is refused rather than silently truncated, on
the date asked for and on each release's ``published`` alike.

``published`` is the only thing 10.3 orders releases by, so a ``published`` the
model would read as some other date is the one input that can make this module
answer wrongly with no refusal and no warning. A number is the case that bites:
pydantic's lax mode reads ``0`` as 1970-01-01, which would resolve every date
against an epoch nobody published on. :class:`Release` therefore refuses a
``published`` whose type is not 10.3's (10.4) rather than coercing it.

Two releases sharing the latest eligible ``published`` are ambiguous: ``release``
is an opaque label (10.1), so no ordering of labels is a meaningful tiebreak and
picking one would be a silent wrong answer. That is refused too, naming the
colliding releases so the caller can narrow the sequence.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator

from hephkit.errors import LAB_412, LAB_424

__all__ = [
    "AmbiguousReleaseError",
    "NoEligibleReleaseError",
    "Release",
    "TemporalError",
    "release_as_of",
]


class TemporalError(LookupError):
    """A release table or a date does not resolve to exactly one release (spec 10.3).

    This module's error base, carrying ``HEPH-LAB-412``: every refusal here is
    about a release table that exists and says something unusable, which is what
    the registry routes to 412. Its subclasses name the specific refusals, and
    :class:`NoEligibleReleaseError` is the absence case at ``HEPH-LAB-424``, so
    one ``except TemporalError`` catches every refusal this module makes and
    ``.code`` is what tells them apart. That is the shape ``lab.config``,
    ``lab.gates`` and :mod:`~hephkit.lab.data.manifest` already use
    (see ``hephkit.lab``'s module docstring for the convention).

    A ``LookupError`` because resolution is what this module does, and because
    a ``ValueError`` could not be raised from :class:`Release`'s validator and
    reach the caller: pydantic converts a ``ValueError`` or ``AssertionError``
    raised in a validator into a ``ValidationError``, which carries no ``.code``,
    and lets anything else through unchanged.
    """

    code = LAB_412


class NoEligibleReleaseError(TemporalError):
    """No release was published on or before the date (``HEPH-LAB-424``).

    The release asked for does not exist, the same "required input is absent"
    that :class:`~hephkit.lab.data.manifest.MissingManifestError` carries. A
    date that precedes every release is this, not the earliest release.
    """

    code = LAB_424


class AmbiguousReleaseError(TemporalError):
    """More than one release shares the latest eligible date (``HEPH-LAB-412``).

    Every input is present and a guard fired, which the registry routes to 412
    as it does :class:`~hephkit.lab.data.manifest.ManifestError`.
    """

    code = LAB_412


class Release(BaseModel):
    """One release of a dataset and the calendar date it was published (10.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    release: str
    published: date

    @field_validator("published", mode="before")
    @classmethod
    def _published_is_a_date_not_a_number(cls, value: object) -> object:
        """10.4: a ``published`` whose type is not 10.3's is invalid, not a date.

        ``strict=True`` is not the way to get this. The JSON string form is
        required -- a release table arrives decoded from JSON or YAML -- and
        strict mode would reject it. So the gate is on the type that arrives:
        the ``full-date`` string, or a ``date`` from Python, and nothing else.

        A ``datetime`` is refused with the rest, although it is a ``date``
        subclass: pydantic would truncate one at midnight to a calendar date,
        and this module's whole subject is that a date is not a moment.
        """
        if isinstance(value, datetime) or not isinstance(value, str | date):
            raise TemporalError(
                f"published must be an RFC 3339 full-date string or a date, "
                f"not {type(value).__name__}: {value!r}"
            )
        return value


def release_as_of(releases: Sequence[Release], when: date) -> Release:
    """Return the latest release published on or before ``when`` (10.3).

    Input order is irrelevant. Raises :class:`NoEligibleReleaseError` when
    nothing qualifies (including an empty table) and
    :class:`AmbiguousReleaseError` when more than one release shares the latest
    eligible ``published``; both are :class:`TemporalError`. A collision among
    releases that are not the latest eligible, or among releases published after
    ``when``, does not matter and does not refuse.

    A ``datetime`` is a subclass of ``date`` whose comparison against a ``date``
    raises, so the guard below names the caller's mistake with a ``TypeError``
    instead of letting an obscure comparison error surface. It is not a coded
    refusal: a wrong argument type is a programming error, not a fact about the
    data.
    """
    if isinstance(when, datetime):
        raise TypeError("release_as_of takes a calendar date, not a datetime")
    eligible = [r for r in releases if r.published <= when]
    if not eligible:
        raise NoEligibleReleaseError(f"no release was published on or before {when.isoformat()}")
    latest = max(r.published for r in eligible)
    tied = sorted(r.release for r in eligible if r.published == latest)
    if len(tied) > 1:
        raise AmbiguousReleaseError(
            f"as of {when.isoformat()} the latest published date {latest.isoformat()} is shared by "
            f"releases {', '.join(tied)}; the resolution is ambiguous"
        )
    return next(r for r in eligible if r.published == latest)
