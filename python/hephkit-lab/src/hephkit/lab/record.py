"""Crash-safe run records and the experiment registry (spec section 8).

:func:`open_record` opens the record of a run, :meth:`RunRecord.append_row`
adds one completed cell to it, :func:`read_record` reads one back, and
:func:`register` and :func:`run` are the registry an experiment announces
itself to. Section 8 is the normative definition of all of it; what follows is
the handful of decisions a reader of this module would otherwise have to infer.

**A row is on disk before ``append_row`` returns.** Every row goes through
:func:`_write_durably`, which writes, flushes the process buffer and
``os.fsync``s the file. The cost of a crash is therefore the row in flight and
nothing else, which is the whole reason this module exists: the design cites
"the failure that lost 881 seconds of the original RL benchmark and led to its
numbers being retyped by hand". It is one function on purpose, so that the
tests can replace it with a buffered write and show that each durability check
fails against the implementation section 8.3 forbids.

**Nothing here degrades on error.** A record that cannot be written is a failed
run, not a quiet one (8.5). Every failure to create the directory, write the
provenance record, append a row or write the summary raises
:class:`RecordError`. There is no warning path, no fallback location and no
dropped row.

**``HEPH-LAB-424``, and where it stops.** 424's registry entry is
"Required record, manifest or frozen input is missing", and its guidance speaks
of "the record of the run being replayed". :func:`read_record` on a record that
is not there is exactly that. A *write* that fails is the same artefact missing
from the other side -- after the failure there is no record, and the fix is to
make the location writable and run again, which is what 424's "Produce it, then
retry" asks for -- and no other LAB code fits it: 409 is a divergence, 412 is a
gate refusing, 422 is the configuration. So :class:`RecordError` carries 424 at
every raise site in this module.

What it deliberately does **not** cover is a record that is there and says
something wrong: a row that is not a row document, a stored summary that
disagrees with the rows, a duplicate cell. 424's own guidance routes those
elsewhere -- "If the artefact exists but says the wrong thing, the code is
HEPH-LAB-412" -- and 412 is the integrity-gate code, whose guidance is written
for a gate refusing an operation. This module sits *below* a gate: it refuses
such a record with a :class:`ValueError` (pydantic's
:class:`~pydantic.ValidationError` where a document fails its model), the way
``lab.repro`` already refuses a malformed provenance record, and ``lab.gates``
is where the same finding becomes a ``HEPH-LAB-412`` violation with a gate
behind it. One ``except ValueError`` therefore catches "this record says
something wrong" and one ``except RecordError`` catches "there is no record",
and neither is spelled as the other.

**Error codes are imported, never spelled.** ``LAB_424`` is generated from
``spec/errors.yaml`` into ``hephkit.errors._codes``;
``tests/test_error_codes.py`` AST-scans this package and fails on a
hand-written literal.

Conventions this module fixes, which section 8 leaves to an implementation:

* **The record is written once.** :func:`open_record` refuses a directory that
  already holds any of the three documents; a resumed run is a new record, not
  an amendment to an old one (8.3 forbids rewriting).
* **A run that fails leaves its record unfinished.** The context manager writes
  the summary only when the body completes, so an experiment that raised
  leaves rows and no summary, which 8.4 defines as unfinished.
* **A non-finite value round-trips.** 8.2's ``{"nonfinite": ...}`` wrapper is
  applied on the way out and undone on the way in, so a diverged loss is
  recorded as itself rather than as a token no conforming JSON parser accepts.
* **A boolean is refused.** It is a number in Python and is neither a number
  nor a string in JSON, and pydantic would coerce ``True`` to ``1.0``: a
  plausible wrong number in a published record.

Maturity: experimental.
"""

from __future__ import annotations

import inspect
import json
import math
import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, Final, TextIO

from hephkit.errors import LAB_424
from hephkit.hashing import canonical_json
from hephkit.lab.repro import ProvenanceRecord
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "NONFINITE",
    "NONFINITE_MEMBER",
    "PROVENANCE_NAME",
    "ROWS_NAME",
    "SUMMARY_NAME",
    "Experiment",
    "RecordError",
    "Row",
    "RunRecord",
    "Summary",
    "encode_value",
    "open_record",
    "read_record",
    "register",
    "registered",
    "run",
]

# Error codes live only in `spec/errors.yaml` (CLAUDE.md). `LAB_424` is
# generated from it and imported rather than re-spelled; the module docstring
# above argues which raise sites it covers and which it does not.

#: The registry code a record that is not there, or that could not be written,
#: carries (spec 8.5, and the reasoning in the module docstring).
CODE = LAB_424

#: The three normative file names of a record directory (spec 8.1).
PROVENANCE_NAME: Final = "provenance.json"
ROWS_NAME: Final = "rows.jsonl"
SUMMARY_NAME: Final = "summary.json"

#: The single member of 8.2's wrapper for a value JSON cannot carry.
NONFINITE_MEMBER: Final = "nonfinite"

#: 8.2's three non-finite spellings, and the values they name.
NONFINITE: Final[dict[str, float]] = {
    "NaN": math.nan,
    "Infinity": math.inf,
    "-Infinity": -math.inf,
}


class RecordError(RuntimeError):
    """There is no record: it could not be written, or it is not there (``HEPH-LAB-424``).

    A ``RuntimeError`` rather than a :class:`hephkit.errors.HephError`, like
    every refusal in ``hephkit.lab``: this is research tooling below research
    code, not behind an HTTP boundary, so it carries no ``status``, ``title``
    or ``type_url`` and ``.code`` is here for correlation and the registry's
    disambiguation (see ``config.py``'s docstring for the full reasoning).
    """

    code = CODE


class Row(BaseModel):
    """One cell's result (spec 8.2): the cell that completed and what it produced.

    Frozen and closed to extras, because 8.2 says a row carries exactly two
    members and a row is the account of work that already happened.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    cell: str = Field(min_length=1)
    values: dict[str, float | str]

    def as_document(self) -> dict[str, Any]:
        """This row as the JSON-ready document 8.2 defines."""
        return {
            "cell": self.cell,
            "values": {name: encode_value(value) for name, value in self.values.items()},
        }


class Summary(BaseModel):
    """A record's summary (spec 8.4): an index over the rows, never a second home.

    Every member is derived from the rows, which is what lets a reader
    recompute it and refuse a stored summary that disagrees.

    ``strict`` as well as closed: 8.4's table gives `rows` as an integer, and
    pydantic's lax mode would validate the string ``"1"`` and the float
    ``1.0`` into it, so a summary a conforming reader in another language
    refuses would be accepted here and then re-serialised as ``1`` -- the
    record would have been repaired on the way in rather than refused. Spec
    3.2 rules out exactly that laxness for money amounts. ``run_id`` and
    ``cells`` refuse a wrong type in lax mode already; strict costs nothing
    and says which rule is in force.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: str
    cells: list[str]
    rows: int

    def as_document(self) -> dict[str, Any]:
        """This summary as the JSON-ready document 8.4 defines."""
        return self.model_dump(mode="json")


#: An experiment: a function of the open record and nothing else (spec 8.6).
Experiment = Callable[["RunRecord"], None]


def _write_durably(handle: TextIO, text: str) -> None:
    """Write `text` to `handle` and hand it to storage before returning (spec 8.3).

    The flush empties the buffer this process owns, so the bytes survive the
    death of the process; the ``fsync`` hands them to the storage device, so
    they survive the machine. 8.3 asks for both, and this is the only place in
    the module that writes anything -- which is what makes it possible to
    demonstrate that a buffering implementation fails the tests rather than
    merely to assert that this one passes them.
    """
    handle.write(text)
    handle.flush()
    os.fsync(handle.fileno())


def encode_value(value: float | str) -> Any:
    """A row value as 8.2 writes it: a string, a finite number, or the wrapper.

    Public because section 9's difference report carries row values too, and a
    report is read: a non-finite one has to leave this package as 8.2's wrapper
    rather than as a token no conforming JSON parser accepts. One encoder, so
    the record and the report cannot drift apart.
    """
    if isinstance(value, str):
        return value
    if math.isfinite(value):
        return value
    spelling = next(name for name, known in NONFINITE.items() if _same(known, value))
    return {NONFINITE_MEMBER: spelling}


def _same(known: float, value: float) -> bool:
    """Whether `value` is `known`, with NaN counted as itself.

    ``nan == nan`` is false, so the lookup that turns a non-finite value into
    its 8.2 spelling cannot be an equality test.
    """
    return math.isnan(known) if math.isnan(value) else known == value


def _decode_value(value: Any, where: str) -> float | str:
    """A row value as 8.2 reads it, undoing the non-finite wrapper."""
    if isinstance(value, dict):
        spelling = value.get(NONFINITE_MEMBER)
        if list(value) != [NONFINITE_MEMBER] or spelling not in NONFINITE:
            raise ValueError(
                f"{where} is an object that is not one of spec 8.2's non-finite "
                f"wrappers: {value!r}"
            )
        return NONFINITE[spelling]
    return value  # type: ignore[no-any-return]


def _checked_values(values: Mapping[str, float | str]) -> dict[str, float | str]:
    """`values` with every boolean refused (spec 8.2).

    A boolean is a number in Python and neither a number nor a string in JSON,
    and pydantic would validate ``True`` into ``1.0``. A published record must
    not carry a number nobody computed.
    """
    for name, value in values.items():
        if isinstance(value, bool):
            raise ValueError(
                f"value {name!r} is a boolean; spec 8.2 allows a number or a string, "
                "and recording `True` as 1.0 would publish a number no cell produced"
            )
    return dict(values)


def _refuse_constant(token: str) -> Any:
    """What ``json.loads`` is told to do with a bare ``NaN`` or ``Infinity``.

    Python's decoder accepts those tokens, and spec 8.2 forbids a record to
    carry one: they are not JSON, 4.3 rejects them, and a conforming parser in
    another language would refuse the file.
    """
    raise ValueError(
        f"the record carries the bare token {token!r}, which is not JSON; spec 8.2 "
        f"records a non-finite value as {{{NONFINITE_MEMBER!r}: ...}}"
    )


def _loads(text: str) -> Any:
    """`text` as JSON, with 8.2's forbidden tokens refused rather than accepted."""
    return json.loads(text, parse_constant=_refuse_constant)


def _write_document(path: Path, document: Mapping[str, Any]) -> None:
    """Write one canonical-JSON document durably, or fail the run (spec 8.1, 8.5).

    Exactly the canonical bytes and no trailing newline, so a hash over the
    file is the content hash (4.2) of the document it holds.
    """
    try:
        with path.open("w", encoding="utf-8") as handle:
            _write_durably(handle, canonical_json(document))
    except OSError as exc:
        raise RecordError(
            f"could not write {path.name} into the record at {path.parent}: {exc}; "
            "a record that cannot be written is a failed run (spec 8.5)"
        ) from exc


def _read_document(path: Path) -> dict[str, Any]:
    """One document of a record, or :class:`RecordError` when it is not there."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RecordError(
            f"{path.name} is missing from the record at {path.parent}, so there is "
            "no record to read (spec 8.1)"
        ) from exc
    except OSError as exc:
        raise RecordError(f"could not read {path}: {exc}") from exc
    document = _loads(text)
    if not isinstance(document, dict):
        raise ValueError(f"{path} does not hold a JSON object (spec 8.1)")
    return document


def _read_rows(path: Path) -> list[Row]:
    """The rows of a record, in the order the file gives them (spec 8.2, 8.3).

    A final line that is not terminated by LF is the row that was in flight
    when the writer died: it was never a complete row, and 8.3 permits a crash
    to cost exactly that one, so it is discarded. Every LF-terminated line must
    be a row document; one that is not means the file has been corrupted or
    edited, and the record is refused rather than read past.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RecordError(
            f"{path.name} is missing from the record at {path.parent}, so there is "
            "no record to read (spec 8.1)"
        ) from exc
    except OSError as exc:
        raise RecordError(f"could not read {path}: {exc}") from exc
    if text and not text.endswith("\n"):
        text = text[: text.rfind("\n") + 1]
    rows: list[Row] = []
    seen: set[str] = set()
    for number, line in enumerate(text.split("\n")[:-1], start=1):
        where = f"{path}:{number}"
        if not line:
            raise ValueError(f"{where} is empty; each line of a record is one row (spec 8.1)")
        document = _loads(line)
        if not isinstance(document, dict):
            raise ValueError(f"{where} does not hold a JSON object (spec 8.1)")
        values = document.get("values")
        if isinstance(values, dict):
            document["values"] = {
                name: _decode_value(value, f"{where} values.{name}")
                for name, value in values.items()
            }
        row = Row.model_validate(document)
        if row.cell in seen:
            raise ValueError(
                f"{where} repeats the cell {row.cell!r}, which spec 8.2 forbids: the "
                "record cannot say which of the two values the run produced"
            )
        seen.add(row.cell)
        rows.append(row)
    return rows


class RunRecord:
    """One run's record on disk (spec 8.1): its provenance, its rows, its summary.

    Built by :func:`open_record` (writable) or :func:`read_record` (read back,
    and closed: 8.3 forbids rewriting a record). An experiment is handed one of
    these and nothing else, so no destination reaches it through its signature
    (8.6). That is the claim, and it is narrower than the one this module was
    harvested from: :attr:`path` is public, so an experiment *can* write a file
    beside the record, and no library in a general-purpose language could stop
    it. What 8.6 buys is that nothing hands it somewhere else to write, which
    is what makes the record the obvious destination rather than one of two.
    """

    def __init__(
        self,
        directory: Path,
        provenance: ProvenanceRecord,
        rows: Iterable[Row] = (),
        handle: TextIO | None = None,
        *,
        complete: bool = False,
    ) -> None:
        self._directory = directory
        self._provenance = provenance
        self._rows = list(rows)
        self._cells = {row.cell for row in self._rows}
        self._handle = handle
        self._complete = complete

    @property
    def path(self) -> Path:
        """The record directory. The runner chose it; the experiment did not (8.6)."""
        return self._directory

    @property
    def provenance(self) -> ProvenanceRecord:
        """The section 7 record of this run, stored unchanged (8.1)."""
        return self._provenance

    @property
    def rows(self) -> tuple[Row, ...]:
        """The rows this record holds -- which is to say the rows on disk."""
        return tuple(self._rows)

    @property
    def complete(self) -> bool:
        """Whether the run reached its end, that is whether a summary was written (8.4)."""
        return self._complete

    def append_row(self, cell: str, values: Mapping[str, float | str]) -> None:
        """Record that `cell` completed with `values`, durably (spec 8.2, 8.3).

        The row reaches the disk before this returns, and is added to
        :attr:`rows` only once it has: a row this record reports is a row the
        file holds (8.5).
        """
        if self._handle is None:
            raise ValueError(
                f"the record at {self._directory} is closed, and spec 8.3 forbids "
                "rewriting one: a resumed run opens a record of its own"
            )
        row = Row(cell=cell, values=_checked_values(values))
        if row.cell in self._cells:
            raise ValueError(
                f"cell {row.cell!r} is already recorded in {self._directory}, which "
                "spec 8.2 forbids: a record cannot name one cell twice"
            )
        try:
            _write_durably(self._handle, canonical_json(row.as_document()) + "\n")
        except OSError as exc:
            raise RecordError(
                f"could not append the row for cell {row.cell!r} to the record at "
                f"{self._directory}: {exc}; a record that cannot be written is a "
                "failed run (spec 8.5)"
            ) from exc
        self._rows.append(row)
        self._cells.add(row.cell)

    def summary(self) -> dict[str, Any]:
        """This record's summary, derived from its rows (spec 8.4)."""
        return Summary(
            run_id=self._provenance.run_id,
            cells=[row.cell for row in self._rows],
            rows=len(self._rows),
        ).as_document()

    def close(self) -> None:
        """Finish the record: write the summary, then stop accepting rows (8.4).

        Idempotent, so a record closed by its context manager may be closed
        again without consequence.
        """
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        self._close_handle(handle)
        _write_document(self._directory / SUMMARY_NAME, self.summary())
        self._complete = True

    def _close_handle(self, handle: TextIO) -> None:
        """Close the rows file, as a failure of the record rather than a bare OSError.

        Closing flushes, and 8.5 says every failure to write a record is raised
        and fails the run. Without this the one write this module does not
        perform itself -- the final flush `close` does -- would escape as a
        plain `OSError`, which is not what the class docstring promises.
        """
        try:
            handle.close()
        except OSError as exc:
            raise RecordError(
                f"could not close {ROWS_NAME} in the record at {self._directory}: "
                f"{exc}; a record that cannot be written is a failed run (spec 8.5)"
            ) from exc

    def _abandon(self, error: BaseException | None = None) -> None:
        """Stop writing without finishing: the run failed, so 8.4 leaves no summary.

        A failure to close is surfaced either way (8.5), by one of two routes,
        and the asymmetry is deliberate rather than an oversight.

        *The run is leaving by an ordinary* :class:`Exception`, *or by nothing.*
        The :class:`RecordError` is raised and replaces it. Python keeps the
        original in the chain, so neither is lost, and a run whose rows may be
        incomplete must not leave its caller told only about the experiment's
        own error -- that is the quiet failure 8.5 forbids.

        *The run is leaving by a* :class:`BaseException` *that is not an*
        :class:`Exception` -- :class:`KeyboardInterrupt`,
        :class:`SystemExit`, :class:`GeneratorExit`. The original propagates
        and the record failure is attached to it as a note. Those exceptions
        sit outside :class:`Exception` precisely so that interpreter-level
        signals are not absorbed by ordinary error handling, and replacing one
        with a ``RuntimeError`` subclass would stop every
        ``except KeyboardInterrupt`` upstream -- the interpreter's own included
        -- from matching it. A researcher's Ctrl-C must stay a Ctrl-C. 8.5 asks
        that the failure reach the caller, not that it displace a signal, and a
        note reaches the caller: the traceback prints it.
        """
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        try:
            self._close_handle(handle)
        except RecordError as failure:
            if error is not None and not isinstance(error, Exception):
                error.add_note(str(failure))
                return
            raise

    def __enter__(self) -> RunRecord:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the record, or abandon it when the run is leaving by an exception.

        A run that ends by failing has not finished, so no summary is written
        and the record stays unfinished (8.4). The exception is never swallowed
        (8.5); :meth:`_abandon` says what happens to it when closing the record
        fails as well, which depends on what the run is leaving by.
        """
        if kind is None:
            self.close()
        else:
            self._abandon(error)


def open_record(directory: Path, provenance: ProvenanceRecord) -> RunRecord:
    """Open the record of a run at `directory` (spec 8.1, 8.3).

    Writes the provenance record and creates the (empty) rows file before
    returning, so a run that dies before its first cell is still the record of
    a run that started. Refuses a directory that already holds a record: 8.3
    forbids rewriting one, so a second run goes somewhere of its own.

    Every failure to create the directory or write into it raises
    :class:`RecordError`: an unwritable record is a failed run (8.5).
    """
    for name in (PROVENANCE_NAME, ROWS_NAME, SUMMARY_NAME):
        if (directory / name).exists():
            raise FileExistsError(
                f"{directory} already holds {name}; spec 8.3 forbids rewriting a "
                "record, so a resumed run opens a record of its own"
            )
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RecordError(
            f"could not create the record directory {directory}: {exc}; a record "
            "that cannot be written is a failed run (spec 8.5)"
        ) from exc
    _write_document(directory / PROVENANCE_NAME, provenance.as_document())
    try:
        handle = (directory / ROWS_NAME).open("a", encoding="utf-8")
    except OSError as exc:
        raise RecordError(
            f"could not open {ROWS_NAME} in the record at {directory}: {exc}; a "
            "record that cannot be written is a failed run (spec 8.5)"
        ) from exc
    return RunRecord(directory, provenance, handle=handle)


def read_record(path: Path) -> RunRecord:
    """Read the record at `path` back (spec 8.1, 8.4).

    A record that is not there is :class:`RecordError`. A record that is there
    and says something wrong -- a line that is not a row document, a repeated
    cell, a stored summary the rows do not support -- is a
    :class:`ValueError`, because the artefact exists and is not a record of
    what it claims (see the module docstring on where ``HEPH-LAB-424`` stops).

    A record holding no summary is unfinished rather than invalid: its rows are
    read and :attr:`RunRecord.complete` is ``False`` (8.4).
    """
    if not path.is_dir():
        raise RecordError(
            f"{path} is not a run record directory, so there is no record to read "
            "(spec 8.1)"
        )
    provenance = ProvenanceRecord.model_validate(_read_document(path / PROVENANCE_NAME))
    rows = _read_rows(path / ROWS_NAME)
    summary_path = path / SUMMARY_NAME
    complete = summary_path.is_file()
    record = RunRecord(path, provenance, rows, complete=complete)
    if complete:
        stored = Summary.model_validate(_read_document(summary_path)).as_document()
        derived = record.summary()
        if stored != derived:
            raise ValueError(
                f"the stored summary of {path} disagrees with its rows, so this is "
                f"not a run record (spec 8.4): {SUMMARY_NAME} says {stored}, the "
                f"rows say {derived}"
            )
    return record


#: The registered experiments, by name. Module state on purpose: a decorator at
#: import time is how an experiment announces itself (8.6).
_EXPERIMENTS: dict[str, Experiment] = {}

#: The parameter kinds an experiment's one parameter may have. A keyword-only
#: parameter is not one: the runner passes the record positionally, and a
#: signature that takes keywords is a signature something else can be passed to.
_RECORD_KINDS: Final = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


def _refuse_a_destination(experiment: Experiment) -> None:
    """Refuse at registration an experiment that could be handed a destination (8.6).

    An experiment takes the open record and nothing else. Anything else in the
    signature -- a second parameter, a default, ``*args``, ``**kwargs`` -- is a
    way for a directory to reach it, and 8.6 requires that to be refused when
    the experiment is registered rather than discovered when it runs.
    """
    parameters = list(inspect.signature(experiment).parameters.values())
    one_record = (
        len(parameters) == 1
        and parameters[0].kind in _RECORD_KINDS
        and parameters[0].default is inspect.Parameter.empty
    )
    if not one_record:
        raise TypeError(
            f"an experiment takes the open record and nothing else (spec 8.6); "
            f"{getattr(experiment, '__name__', experiment)!r} takes "
            f"{[str(p) for p in parameters]}"
        )


def register(name: str) -> Callable[[Experiment], Experiment]:
    """Register an experiment under `name` (spec 8.6).

    Used as a decorator. The function is returned unchanged, so an experiment
    stays an ordinary callable its own tests can call with a record.
    """

    def decorate(experiment: Experiment) -> Experiment:
        _refuse_a_destination(experiment)
        if name in _EXPERIMENTS:
            raise ValueError(
                f"experiment {name!r} is already registered; a name identifies one "
                "experiment, and a record names the experiment that produced it"
            )
        _EXPERIMENTS[name] = experiment
        return experiment

    return decorate


def registered() -> dict[str, Experiment]:
    """The registered experiments, as a copy: the registry itself is not handed out."""
    return dict(_EXPERIMENTS)


def run(name: str, directory: Path, *, provenance: ProvenanceRecord) -> RunRecord:
    """Run the registered experiment `name`, recording it at `directory` (8.6).

    The runner opens the record, chooses where it goes, passes it to the
    experiment and closes it. The experiment receives the record and no
    destination, which is what makes "a number cannot exist without a record"
    structural rather than a habit (8.1, 8.6).

    `provenance` is the section 7 record of this run, which section 8 stores
    and never computes: capturing it is ``lab.repro.capture``'s business, and a
    runner that captured one here would have to invent the config and data
    hashes it needs.

    An experiment that raises is not caught: its record is left unfinished
    (8.4) and the exception reaches the caller (8.5).
    """
    try:
        experiment = _EXPERIMENTS[name]
    except KeyError:
        raise KeyError(
            f"no experiment named {name!r} is registered; registered: "
            f"{sorted(_EXPERIMENTS)}"
        ) from None
    with open_record(directory, provenance) as record:
        experiment(record)
    return record
