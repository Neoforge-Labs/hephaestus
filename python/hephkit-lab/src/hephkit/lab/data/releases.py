"""Date-to-release resolution (spec 10.3).

A dated run must evaluate the population that date would have evaluated, so a
date resolves to the latest release published on or before it and never to one
published after. :func:`release_as_of` refuses when no release qualifies: a
date that precedes every release is not answered with the earliest release,
because that release is itself from the future of the date.

The resolver filters first and chooses second, so a release published after
the date is never a candidate and no ordering of the input can make it one.
Both sides are RFC 3339 ``full-date``s compared as calendar dates; a
``datetime`` is not a date and is refused rather than silently truncated.

Two releases sharing the latest eligible ``published`` are ambiguous: ``release``
is an opaque label (10.1), so no ordering of labels is a meaningful tiebreak and
picking one would be a silent wrong answer. That is refused too, naming the
colliding releases so the caller can narrow the sequence.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from hephkit.errors import LAB_412, LAB_424

__all__ = ["AmbiguousReleaseError", "Release", "TemporalError", "release_as_of"]


class TemporalError(LookupError):
    """A date does not resolve to exactly one release (spec 10.3).

    Raised bare, with ``HEPH-LAB-424``, when no release was published on or
    before the date: the release asked for does not exist, the same "required
    input is absent" that :class:`~hephkit.lab.data.manifest.MissingManifestError`
    carries. :class:`AmbiguousReleaseError` is the subclass for the other
    refusal, so ``except TemporalError`` catches both.
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


def release_as_of(releases: Sequence[Release], when: date) -> Release:
    """Return the latest release published on or before ``when`` (10.3).

    Input order is irrelevant. Raises :class:`TemporalError` when nothing
    qualifies (including an empty table) and :class:`AmbiguousReleaseError` when
    more than one release shares the latest eligible ``published``. A collision among releases that are not
    the latest eligible, or among releases published after ``when``, does not
    matter and does not refuse.

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
        raise TemporalError(f"no release was published on or before {when.isoformat()}")
    latest = max(r.published for r in eligible)
    tied = sorted(r.release for r in eligible if r.published == latest)
    if len(tied) > 1:
        raise AmbiguousReleaseError(
            f"as of {when.isoformat()} the latest published date {latest.isoformat()} is shared by "
            f"releases {', '.join(tied)}; the resolution is ambiguous"
        )
    return next(r for r in eligible if r.published == latest)
