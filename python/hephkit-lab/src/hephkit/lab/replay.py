"""Re-execute a recorded run and diff the result (spec section 9).

:func:`replay` reads a record, re-runs the experiment that produced it and
hands back a :class:`DiffReport`; :func:`compare` is the comparison on its own,
over two records that are already in hand. Section 9 is the normative
definition of all of it, and `conformance/lab/diff.json` pins every case of the
comparison. What follows is the handful of decisions a reader of this module
would otherwise have to infer.

**A divergence is reported, never raised.** The design quotes NeoRx: "A replay
that differs is not a failure of the tool -- it names exactly which values
moved, which is the information a reviewer actually needs." So :func:`replay`
returns a report whether or not it matched, and 9.1 forbids refusing in place
of producing one.

**Which situations therefore raise, and under which code.** Read
``spec/errors.yaml`` rather than the plan here, because the plan's wording and
the registry's disagree.

* ``HEPH-LAB-424`` is "Required record, manifest or frozen input is missing",
  and its guidance names "the record of the run being replayed" as its own
  example. A record that is not there is therefore :class:`RecordError` from
  ``lab.record``, and this module does **not** re-wrap it: a second code for
  the registry's own example would make its disambiguation meaningless.
* An experiment name that is **not registered** raises ``KeyError`` from
  :func:`hephkit.lab.record.run`. That is a programming error in the caller --
  the name is a literal in its own source -- and ``lab.record`` settled the
  refusal; the plan proposed ``ReplayError`` for it, but 409 is a divergence
  and 424 is an absent artefact, and an unregistered name is neither.
* ``HEPH-LAB-409`` is "Replay diverged from its record", and its detail hint is
  "The difference report names every value that differs". That is exactly one
  situation: a report that did not match, in the hands of a caller who wants a
  refusal rather than a finding. :meth:`DiffReport.raise_if_diverged` is that
  caller's one line, it carries the report on the error, and it is the only
  raise site of :class:`ReplayError` in this module. Making it a method of the
  report rather than a mode of :func:`replay` is deliberate: a replay produces
  a report, and nothing about calling this can change that.

**The re-execution's provenance is the caller's, not the record's.** This is
why :func:`replay` takes a ``provenance`` keyword the planned signature did not
have. Four of the things 9.1 compares are ``config_hash``, ``data_hash``,
``deps_hash`` and ``code_sha``; if this function filled them in from the record
it is replaying, all four would be equal by construction and four of the five
comparisons could never fail. Capturing them is ``lab.repro.capture``'s
business and the caller's call -- it is the one that knows which configuration
and which data this replay is pointed at -- exactly as ``lab.record.run`` takes
the provenance of a first run rather than inventing one.

``into`` is required for the same reason ``lab.record.run`` takes a directory:
the re-execution is a run, 8.1 says a number cannot exist without a record, and
8.6 says the runner chooses where that record goes rather than the experiment.

**Freezing inputs is a later module.** ``lab.sources`` is wave 2, so a replay
here re-executes the registered experiment against whatever inputs it meets and
compares what 9.1 says to compare. A match is evidence that the experiment
reproduced under those inputs; what carries their identity is ``data_hash``,
which is compared like every other member of the determinism contract.

**One comparison, in one place.** :func:`values_match` is the whole of 9.3, and
:data:`COMPARED_MEMBERS` is the whole of "which members of the provenance
record a replay compares". Both are module-level on purpose: a test can replace
either and show that the check which passes against this module fails against
the implementation section 9 forbids. "``environment`` is not compared" is
otherwise a claim that passes against an implementation comparing nothing.

**``NaN`` compares equal to ``NaN``** (9.3). A record exists to be compared
against, so a diverged loss must compare equal to itself; ``==`` says otherwise
and would make a replay report a difference between a run and that same run.

**A ``null`` equals a ``null``** (9.3), at the two member positions 7.1 lets be
one. That is the same shape as the NaN rule one position over, and it is the
ordinary case rather than an exotic one: 7.3 makes a ``null`` ``deps_hash`` and
a ``null`` ``code_sha`` exactly what a ``provenance-only`` run carries, so an
implementation letting a ``null`` match nothing would call every replay of one
diverged.

**A re-execution whose experiment raises produces no report** (9.1). The
exception reaches the caller and the partial record is left where it is,
unfinished (8.4), because it says how far the re-execution got. Returning a
report that called the missing cells a divergence is the one thing 9.1 forbids
here.

Maturity: experimental.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

from hephkit.errors import LAB_409
from hephkit.lab.record import RunRecord, encode_value, read_record, run
from hephkit.lab.repro import ProvenanceRecord
from pydantic import BaseModel, ConfigDict, model_validator

__all__ = [
    "ABSOLUTE_TOLERANCE",
    "COMPARED_MEMBERS",
    "RELATIVE_TOLERANCE",
    "DiffReport",
    "Difference",
    "ReplayError",
    "Value",
    "compare",
    "members_match",
    "replay",
    "values_match",
]

# Error codes live only in `spec/errors.yaml` (CLAUDE.md). `LAB_409` is
# generated from it and imported rather than re-spelled; the module docstring
# above argues which situation it covers and which ones it does not.

#: The registry code for a replay that diverged from its record (spec 9.4).
CODE = LAB_409

#: The members of the provenance record a replay compares: the determinism
#: contract of spec 7.1, in that table's order (9.1). `environment`, `run_id`
#: and `class` are absent, each for a reason 9.1 gives separately.
COMPARED_MEMBERS: Final[tuple[str, ...]] = ("config_hash", "data_hash", "deps_hash", "code_sha")

#: The relative half of 9.3's float tolerance.
RELATIVE_TOLERANCE: Final = 1e-9

#: The absolute half of 9.3's float tolerance: the floor that makes a
#: comparison near zero mean anything at all.
ABSOLUTE_TOLERANCE: Final = 1e-12

#: A row value, or `None` for a position one side does not hold (9.2).
Value = float | str | None


class ReplayError(RuntimeError):
    """A replay diverged from its record (``HEPH-LAB-409``).

    Raised only by :meth:`DiffReport.raise_if_diverged`, for a caller that
    needs a refusal rather than a finding (9.4). :attr:`report` is the report,
    because the registry's detail hint for this code is that the report names
    every value that differs.

    A ``RuntimeError`` rather than a :class:`hephkit.errors.HephError`, like
    every refusal in ``hephkit.lab``: this is research tooling below research
    code, not behind an HTTP boundary, so it carries no ``status``, ``title``
    or ``type_url`` and ``.code`` is here for correlation and the registry's
    disambiguation.
    """

    code = CODE

    def __init__(self, message: str, report: DiffReport) -> None:
        super().__init__(message)
        self.report = report


class Difference(BaseModel):
    """One position where the record and the re-execution disagree (spec 9.2).

    `cell` is `None` when the position is a member of the determinism
    contract, and `key` is then that member's name. `key` is `None` for a cell
    that holds no values and is on one side only, which is the one difference
    carrying `None` on both sides.

    Frozen and closed to extras, because a difference is the account of a
    comparison that already happened. ``strict`` as well: in lax mode pydantic
    would validate the string ``"0.5"`` into the ``float`` of this union, and
    9.3 compares by kind first -- a number and a string at one position are a
    difference, and a report that had quietly turned one into the other would
    be reporting a comparison nobody made.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cell: str | None
    key: str | None
    recorded: Value
    replayed: Value

    def as_document(self) -> dict[str, Any]:
        """This difference as a JSON-ready document, in 9.2's member order.

        A non-finite value is written as 8.2's wrapper, by 8.2's own encoder:
        a report is read, and the bare tokens some encoders emit are not JSON.
        """
        return {
            "cell": self.cell,
            "key": self.key,
            "recorded": _encoded(self.recorded),
            "replayed": _encoded(self.replayed),
        }


class DiffReport(BaseModel):
    """What a replay produces (spec 9.2): whether it matched, and what moved.

    `record_unfinished` is true when the record the replay compared holds no
    summary, which 8.4 defines as unfinished. Such a record holds only the
    cells its run reached, so every cell the run never reached is a position
    only the re-execution holds and the report carries a difference for a
    value that never moved. 9.2 keeps those differences -- they are true
    statements about the two records -- and requires this member so that a
    reader can tell a cell that never ran from a value that appeared.

    Frozen and closed to extras. `differences` is a tuple rather than a list
    so that the report a caller holds is the report this module built.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    matched: bool
    record_unfinished: bool
    differences: tuple[Difference, ...]

    @model_validator(mode="after")
    def _matched_exactly_when_there_is_no_difference(self) -> DiffReport:
        """9.2: never a match alongside a difference, nor a divergence with none."""
        if self.matched != (self.differences == ()):
            raise ValueError(
                f"a report is matched if and only if it carries no difference (spec "
                f"9.2); this one says matched={self.matched} with "
                f"{len(self.differences)} difference(s)"
            )
        return self

    def as_document(self) -> dict[str, Any]:
        """This report as a JSON-ready document, in 9.2's order."""
        return {
            "matched": self.matched,
            "record_unfinished": self.record_unfinished,
            "differences": [difference.as_document() for difference in self.differences],
        }

    def raise_if_diverged(self) -> None:
        """Refuse if this report did not match (``HEPH-LAB-409``, spec 9.4).

        The one line a caller that needs a refusal rather than a finding
        writes: a gate asking whether a cited run still reproduces. A replay
        itself never does this (9.1), and the refusal names the positions,
        because the naming is the finding.
        """
        if self.matched:
            return
        where = ", ".join(_position(difference) for difference in self.differences)
        raise ReplayError(
            f"the replay diverged from its record at {len(self.differences)} "
            f"position(s): {where}",
            self,
        )


def _position(difference: Difference) -> str:
    """How one position reads in a refusal: `cell.key`, or the member name."""
    if difference.cell is None:
        return str(difference.key)
    return f"{difference.cell}.{difference.key}" if difference.key is not None else difference.cell


def _encoded(value: Value) -> Any:
    """A difference's side as a document, with `None` passed through.

    `None` is not a row value (8.2), so it reaches 8.2's encoder from nowhere
    else: at a row position it says the position is absent, and at one of the
    four members it is the member's own value (9.2).
    """
    return None if value is None else encode_value(value)


def values_match(recorded: float | str, replayed: float | str) -> bool:
    """Whether two row values are equal under spec 9.3.

    Kind first: a string equals only an identical string, so a string against a
    number is a difference however alike the two look. Then the non-finite
    values, each compared by the value 8.2's wrapper names, which is what makes
    ``NaN`` equal to ``NaN`` and ``Infinity`` different from ``-Infinity``.
    Then the tolerance, which is the only inexact comparison in this module.

    The non-finite cases cannot be left to the tolerance: ``inf - inf`` is
    ``nan`` and ``nan <= x`` is false, so every infinity would differ from
    itself.
    """
    if isinstance(recorded, str) or isinstance(replayed, str):
        return recorded == replayed
    if math.isnan(recorded) or math.isnan(replayed):
        return math.isnan(recorded) and math.isnan(replayed)
    if math.isinf(recorded) or math.isinf(replayed):
        return recorded == replayed
    return abs(recorded - replayed) <= max(
        RELATIVE_TOLERANCE * max(abs(recorded), abs(replayed)), ABSOLUTE_TOLERANCE
    )


def members_match(recorded: str | None, replayed: str | None) -> bool:
    """Whether two determinism-contract members are equal under spec 9.3.

    Exactly, and `None` equals `None`. 9.3 makes a `null` a fourth kind that
    equals a `null` and nothing else, and 7.1 makes `deps_hash` and `code_sha`
    the two members that may be one: two records that both had no lockfile, or
    whose code no git commit names, do not differ there, because there is no
    value either side ever had. 7.3 makes those nulls exactly what a
    ``provenance-only`` run carries, so this is the ordinary case and not an
    exotic one -- it is the same shape as 9.3's NaN rule, one member position
    over, and an implementation that let a `null` match nothing would report
    every replay of a `provenance-only` run as diverged at `deps_hash`.

    Module-level for the reason :func:`values_match` is: a test replaces it
    with the implementation 9.3 forbids and shows that the check which passes
    against this module fails against that one.

    9.3's tolerance has no part in this. A member is a content hash, a commit
    SHA or a `null`, and the tolerance is about numbers a run produced.
    """
    return recorded == replayed


def _compared(provenance: ProvenanceRecord) -> dict[str, Any]:
    """The members of `provenance` a replay compares, by name (spec 9.1).

    Read off :meth:`ProvenanceRecord.as_document`, so what is compared is the
    value an implementation in another language would read out of
    ``provenance.json`` rather than a Python attribute that happens to shadow
    it.
    """
    document = provenance.as_document()
    return {member: document[member] for member in COMPARED_MEMBERS}


def _member_differences(
    recorded: ProvenanceRecord, replayed: ProvenanceRecord
) -> Iterator[Difference]:
    """9.1: the determinism contract, in the order of 7.1's table.

    :func:`members_match` is 9.3 at a member position, the `null` rule
    included.
    """
    left, right = _compared(recorded), _compared(replayed)
    for member, value in left.items():
        if not members_match(value, right[member]):
            yield Difference(cell=None, key=member, recorded=value, replayed=right[member])


def _cells(record: RunRecord) -> dict[str, Mapping[str, float | str]]:
    """A record's rows by cell name, in file order.

    Keyed by name because 9.1 does not compare the order of the rows, and 8.2
    makes a cell name unique within a record, which a reader has already
    enforced.
    """
    return {row.cell: row.values for row in record.rows}


def _row_differences(recorded: RunRecord, replayed: RunRecord) -> Iterator[Difference]:
    """9.2's row positions: the record's first, then the re-execution's own.

    Two passes rather than one per cell, because 9.2 orders every position the
    record holds before every position only the re-execution holds -- not each
    cell's together.
    """
    left, right = _cells(recorded), _cells(replayed)
    for cell, values in left.items():
        other = right.get(cell)
        if other is None:
            yield from _one_sided(cell, values, recorded_side=True)
            continue
        for key, value in values.items():
            if key not in other:
                yield Difference(cell=cell, key=key, recorded=value, replayed=None)
            elif not values_match(value, other[key]):
                yield Difference(cell=cell, key=key, recorded=value, replayed=other[key])
    for cell, values in right.items():
        if cell in left:
            yield from (
                Difference(cell=cell, key=key, recorded=None, replayed=value)
                for key, value in values.items()
                if key not in left[cell]
            )
        else:
            yield from _one_sided(cell, values, recorded_side=False)


def _one_sided(
    cell: str, values: Mapping[str, float | str], *, recorded_side: bool
) -> Iterator[Difference]:
    """A cell only one side holds (spec 9.2).

    One difference per value it holds, so every unaccounted-for value is
    named. A cell holding no values -- 8.2 permits an empty ``values`` -- has
    no ``(cell, key)`` position at all, and would otherwise vanish from the
    report; it is the one difference with `None` on both sides.
    """
    if not values:
        yield Difference(cell=cell, key=None, recorded=None, replayed=None)
        return
    for key, value in values.items():
        yield Difference(
            cell=cell,
            key=key,
            recorded=value if recorded_side else None,
            replayed=None if recorded_side else value,
        )


def compare(recorded: RunRecord, replayed: RunRecord) -> DiffReport:
    """Diff two records, as spec 9 defines it.

    Compares the determinism contract of each record's provenance record and
    the rows, by cell name and value name, and nothing else: not
    ``environment``, not ``run_id``, not ``class``, not the summary and not the
    order of the rows (9.1).

    The summary is not compared because every member of it is derived from the
    rows (8.4) and :func:`hephkit.lab.record.read_record` has already refused a
    record whose stored summary disagrees with them, so comparing it would
    compare the rows a second time under another name.

    `record_unfinished` comes from the **recorded** side: it is that record
    whose unreached cells the report would otherwise present as values that
    appeared (9.2). Whether the re-execution finished is not a fact about the
    comparison -- a re-execution that did not finish is a failed run, which
    9.1 says produces no report at all.

    Pure: nothing is written and neither record is touched, so a report may be
    recomputed from the same two records and read the same way.
    """
    differences = (
        *_member_differences(recorded.provenance, replayed.provenance),
        *_row_differences(recorded, replayed),
    )
    return DiffReport(
        matched=not differences,
        record_unfinished=not recorded.complete,
        differences=differences,
    )


def replay(
    record: Path, *, experiment: str, into: Path, provenance: ProvenanceRecord
) -> DiffReport:
    """Re-execute the run at `record` and diff the result (spec 9.1).

    `experiment` is the name the experiment registered under (8.6); `into` is
    where the re-execution's own record goes, which the runner chooses and the
    experiment never sees; `provenance` is the section 7 record of the
    re-execution, captured by the caller. The module docstring says why the
    last two are not optional and why `provenance` is not taken from `record`.

    The record is read before anything runs, so a record that is not there
    costs nothing and raises :class:`hephkit.lab.record.RecordError`
    (``HEPH-LAB-424``) rather than leaving a re-execution behind. A divergence
    is returned, not raised.

    The re-execution's record is **read back from disk** rather than compared
    as the live object :func:`hephkit.lab.record.run` returns. 9.2 orders a
    report by the member order of each row's ``values``, and 8.1 makes that the
    canonical order (4.1) only once the row has been written: the live object
    holds the order the experiment happened to produce. Reading it back is also
    what the record will be read as when it is published, and it puts the
    re-execution through the same reader -- 8.4's summary check included -- as
    the record it is compared against.
    """
    recorded = read_record(record)
    written = run(experiment, into, provenance=provenance)
    return compare(recorded, read_record(written.path))
