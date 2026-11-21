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
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from hephkit.errors import LAB_424

__all__ = ["Release", "TemporalError", "release_as_of"]


class TemporalError(LookupError):
    """No release was published on or before the date (``HEPH-LAB-424``)."""

    code = LAB_424


class Release(BaseModel):
    """One release of a dataset and the calendar date it was published (10.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    release: str
    published: date


def release_as_of(releases: Sequence[Release], when: date) -> Release:
    """Return the latest release published on or before ``when`` (10.3).

    Input order is irrelevant. Two releases published on the same date resolve
    to the one whose ``release`` label sorts last, so the answer does not depend
    on which was listed first. Raises :class:`TemporalError` when nothing
    qualifies, including for an empty table.
    """
    if isinstance(when, datetime):
        raise TypeError("release_as_of takes a calendar date, not a datetime")
    eligible = [r for r in releases if r.published <= when]
    if not eligible:
        raise TemporalError(f"no release was published on or before {when.isoformat()}")
    return max(eligible, key=lambda r: (r.published, r.release))
