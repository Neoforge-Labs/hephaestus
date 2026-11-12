"""Run records: structure, incremental writes and the registry (spec section 8).

Design 9.3 gives this module **contract tests** rather than JSON vectors,
because its behaviour is about effects on the world: no input/output pair can
express "the completed rows survive a kill -9". So there is no
``conformance/lab/record.json`` case for anything here, and the burden moves
onto these tests to be the kind that can fail.

Three habits make that checkable rather than claimed.

**Every durability claim is paired with the implementation that breaks it.**
``_write_durably`` is the one function through which a row reaches storage, so a
test can replace it with a write that leaves the bytes in this process's buffer
-- which is precisely "an implementation that buffers rows instead of flushing
them" -- and assert that the same check which passes against the real module
fails against that one. Two tests here exist only to demonstrate the bite of
their neighbour, in-process for 8.3's "before the call returns" and across a
hard ``os._exit`` for the crash contract.

**The kill is a real kill.** The crash test runs a child interpreter that
appends rows and then calls ``os._exit(1)``, which skips every exit hook and
every buffer flush Python would otherwise perform. A clean ``sys.exit`` would
flush the rows on the way out and the test would pass against a buffering
implementation, which is the defect this suite is written against.

**"Raises rather than warns" asserts both halves.** ``filterwarnings =
["error"]`` in ``pyproject.toml`` would turn a ``warnings.warn`` into an
exception, so a test that only asserted "something was raised" would pass
against an implementation that warned. Each of those tests therefore installs
``simplefilter("always")`` for its duration -- making a warning harmless again
-- and then asserts both that the call raised and that nothing was warned.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import subprocess
import sys
import warnings
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, TextIO

import env_rules
import pytest
from hephkit.errors import LAB_424
from hephkit.hashing import canonical_json
from hephkit.lab import record as record_module
from hephkit.lab.record import (
    PROVENANCE_NAME,
    ROWS_NAME,
    SUMMARY_NAME,
    RecordError,
    RunRecord,
    open_record,
    read_record,
    register,
    registered,
    run,
)
from hephkit.lab.repro import ProvenanceRecord, capture
from pydantic import ValidationError

# Two content hashes (spec 4.2) standing in for the canonical config and the
# dataset digest, quoted from `conformance/hashing/content.json` (`empty-object`
# and `null`) so no hash string in this file is of unknown origin. Section 8
# never reads either one: it stores the section 7 record it is handed.
CONFIG_HASH = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
DATA_HASH = "sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"


def a_provenance(run_id: str = "run-0001") -> ProvenanceRecord:
    """A section 7 record, built by hand rather than captured.

    Hand-built on purpose: the record tests are about what section 8 does with
    a provenance record, and a captured one would make every assertion here
    depend on the machine the suite runs on. The one test that needs a real
    capture -- the 7.5 scan over what a record writes -- calls `capture`.
    """
    return ProvenanceRecord.model_validate(
        {
            "run_id": run_id,
            "config_hash": CONFIG_HASH,
            "data_hash": DATA_HASH,
            "deps_hash": None,
            "code_sha": None,
            "class": "provenance-only",
            "environment": {
                "platform": "linux-x86_64",
                "python": "3.12.7",
                "frameworks": {"numpy": None},
                "accelerator": None,
            },
        }
    )


def buffered(handle: TextIO, text: str) -> None:
    """A write that leaves the bytes in this process: no flush, no fsync.

    The implementation 8.3 forbids, used by the two demonstration tests below
    so that each durability check is shown to fail against it rather than only
    to pass against the real one.
    """
    handle.write(text)


def rows_text(record: RunRecord) -> str:
    """The bytes of the record's rows file, read back through the filesystem."""
    return (record.path / ROWS_NAME).read_text(encoding="utf-8")


def rows_on_disk(directory: Path) -> list[dict[str, Any]]:
    """Every row readable from `directory` right now, parsed strictly.

    `parse_constant` is what makes this strict: `json.loads` accepts the bare
    tokens `NaN` and `Infinity` by default, which spec 8.2 forbids a record to
    carry, so a reader that is meant to prove a record is parseable elsewhere
    must refuse them here too.
    """
    path = directory / ROWS_NAME
    if not path.exists():
        return []
    return [
        json.loads(line, parse_constant=_refuse_constant)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _refuse_constant(token: str) -> Any:
    raise AssertionError(f"the record carries the bare token {token!r}, which is not JSON")


@pytest.fixture
def clean_registry() -> Iterator[None]:
    """Leave the process-wide experiment registry as it was found.

    The registry is module state by design -- a decorator at import time is how
    an experiment announces itself -- so a test that registered a name would
    otherwise leak it into every test after it.
    """
    saved = dict(registered())
    try:
        yield
    finally:
        record_module._EXPERIMENTS.clear()
        record_module._EXPERIMENTS.update(saved)


# --- 8.1: what a record is -----------------------------------------------------


def test_a_record_is_a_directory_holding_the_three_documents(tmp_path: Path) -> None:
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("cell-a", {"loss": 1.5})
    assert record.path == tmp_path / "record"
    assert sorted(p.name for p in record.path.iterdir()) == sorted(
        [PROVENANCE_NAME, ROWS_NAME, SUMMARY_NAME]
    )


def test_an_open_record_has_its_two_files_before_the_first_row(tmp_path: Path) -> None:
    """8.3: `rows.jsonl` exists, possibly empty, from the moment a record is open.

    Asserted directly rather than left to the `== []` assertions elsewhere:
    `rows_on_disk` reports an absent file as no rows, so a record that deferred
    creating the file would satisfy those and fail this one -- at the clause it
    actually breaks.
    """
    record = open_record(tmp_path / "record", a_provenance())
    assert (record.path / PROVENANCE_NAME).is_file()
    assert (record.path / ROWS_NAME).is_file(), "8.3: the rows file exists from the start"
    assert (record.path / ROWS_NAME).read_bytes() == b""
    assert read_record(record.path).rows == ()
    record.close()


def test_the_provenance_document_is_the_section_7_record_unchanged(tmp_path: Path) -> None:
    """8.1: stored unchanged, so 7.1's closed member set stays closed."""
    provenance = a_provenance()
    with open_record(tmp_path / "record", provenance):
        pass
    stored = json.loads((tmp_path / "record" / PROVENANCE_NAME).read_text(encoding="utf-8"))
    assert stored == provenance.as_document()


def test_every_document_in_a_record_is_canonical_json(tmp_path: Path) -> None:
    """8.1: canonical JSON (4.1), so one run's record is one set of bytes."""
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("b", {"z": 2.0, "a": 1.0})
        record.append_row("a", {})
    for name in (PROVENANCE_NAME, SUMMARY_NAME):
        text = (record.path / name).read_text(encoding="utf-8")
        assert text == canonical_json(json.loads(text)), name
    lines = rows_text(record).splitlines()
    assert lines == [canonical_json(json.loads(line)) for line in lines]
    assert rows_text(record).endswith("\n"), "8.1: each line ends in a single LF"


def test_each_document_carries_exactly_the_members_section_8_defines(tmp_path: Path) -> None:
    """8.2 and 8.4's member sets, which is also what forbids a wall-clock member.

    8.1 says a record carries no wall-clock time under any member name. The
    honest way to check that is not a blacklist of time-ish names but the
    member sets themselves: if each document carries exactly the members its
    table defines, there is nowhere for a timestamp to be.
    """
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("cell-a", {"loss": 1.5})
    for row in rows_on_disk(record.path):
        assert sorted(row) == ["cell", "values"]
    summary = json.loads((record.path / SUMMARY_NAME).read_text(encoding="utf-8"))
    assert sorted(summary) == ["cells", "rows", "run_id"]
    assert sorted(record.summary()) == ["cells", "rows", "run_id"]


def test_the_documents_a_record_writes_carry_no_fact_7_5_forbids(tmp_path: Path) -> None:
    """A real capture, so `environment` is this machine's rather than a fixture's.

    `env_rules` is the repository's one statement of what checking 7.5 means,
    and a record is the artefact 7.5 was written about: it is committed and
    published alongside the result. Section 8 writes two documents of its own
    beside it, so the scan runs over all three.
    """
    provenance = capture(
        run_id="run-7-5",
        config_hash=CONFIG_HASH,
        data_hash=DATA_HASH,
        repo=tmp_path / "no-such-tree",
    )
    with open_record(tmp_path / "record", provenance) as record:
        record.append_row("cell-a", {"loss": 1.5})
    for name in (PROVENANCE_NAME, SUMMARY_NAME):
        document = json.loads((record.path / name).read_text(encoding="utf-8"))
        assert env_rules.forbidden_facts(document) == [], name
    for row in rows_on_disk(record.path):
        assert env_rules.forbidden_facts(row) == []


# --- 8.3: rows reach the disk as cells complete --------------------------------


def test_rows_are_on_disk_before_the_run_ends(tmp_path: Path) -> None:
    """8.3: durable before the call that appended the row returns.

    Read back through the filesystem, not from the record object, and asserted
    while the record is still open: an implementation that assembled the file
    at the end would satisfy neither.
    """
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("first", {"loss": 1.5})
        assert rows_on_disk(record.path) == [{"cell": "first", "values": {"loss": 1.5}}]
        record.append_row("second", {"loss": 0.5, "name": "resnet"})
        assert rows_on_disk(record.path) == [
            {"cell": "first", "values": {"loss": 1.5}},
            {"cell": "second", "values": {"loss": 0.5, "name": "resnet"}},
        ]


def test_the_on_disk_check_fails_against_a_record_that_buffers_its_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bite of the test above, demonstrated rather than assumed.

    With the one durable write replaced by a plain buffered write, the row is
    nowhere on disk when `append_row` returns, so the assertion the previous
    test makes is an assertion that can fail.
    """
    monkeypatch.setattr(record_module, "_write_durably", buffered)
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("first", {"loss": 1.5})
        assert rows_on_disk(record.path) == [], "the buffering stand-in is not buffering"


# --- the crash contract: a kill costs the in-flight row, not the run -----------

#: A child run: open a record, append two rows, die without flushing anything.
#: `os._exit` skips every exit hook and every buffer flush, which is what makes
#: this a kill rather than an exit -- a `sys.exit` would flush the rows on the
#: way out and the assertion would hold against a buffering implementation too.
CRASH_PROGRAM = """
import json, os, sys
from pathlib import Path

from hephkit.lab import record as record_module
from hephkit.lab.repro import ProvenanceRecord

directory, mode, document = sys.argv[1], sys.argv[2], sys.argv[3]
if mode == "buffer":
    def buffered(handle, text):
        handle.write(text)
    record_module._write_durably = buffered

provenance = ProvenanceRecord.model_validate(json.loads(document))
run = record_module.open_record(Path(directory), provenance)
run.append_row("first", {"loss": 1.5})
run.append_row("second", {"loss": 0.5})
os._exit(1)
"""


def crash(directory: Path, mode: str) -> None:
    """Run `CRASH_PROGRAM` to its death, asserting it died the way it meant to."""
    done = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [
            sys.executable,
            "-c",
            CRASH_PROGRAM,
            str(directory),
            mode,
            json.dumps(a_provenance().as_document()),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1, f"the child did not reach its kill:\n{done.stderr}"
    # An uncaught exception also exits 1, so the status alone does not say the
    # child reached `os._exit`. A silent stderr does.
    assert done.stderr == "", f"the child died of something else:\n{done.stderr}"


def test_killing_the_process_mid_run_keeps_completed_rows(tmp_path: Path) -> None:
    """8.3: every cell that completed before the kill is on disk and readable."""
    directory = tmp_path / "record"
    crash(directory, "durable")
    assert rows_on_disk(directory) == [
        {"cell": "first", "values": {"loss": 1.5}},
        {"cell": "second", "values": {"loss": 0.5}},
    ]
    record = read_record(directory)
    assert [row.cell for row in record.rows] == ["first", "second"]
    assert not record.complete, "8.4: a killed run leaves an unfinished record"


def test_the_crash_check_fails_against_a_record_that_buffers_its_rows(tmp_path: Path) -> None:
    """The bite of the test above: the same kill against a buffering writer.

    Both rows are lost, which is the 881 seconds the design cites. It also
    proves the kill is a real kill: a child that flushed on the way out would
    leave the rows here too, and this assertion would fail.
    """
    directory = tmp_path / "record"
    crash(directory, "buffer")
    assert rows_on_disk(directory) == []
    # The provenance document survives: it is written and closed before the
    # first row, so the loss is the rows and nothing else.
    assert (directory / PROVENANCE_NAME).is_file()


# --- 8.4: the summary is derived, and a disagreeing one is refused -------------


def test_the_summary_is_what_the_rows_say(tmp_path: Path) -> None:
    with open_record(tmp_path / "record", a_provenance("run-42")) as record:
        assert record.summary() == {"run_id": "run-42", "cells": [], "rows": 0}
        record.append_row("b", {"loss": 1.0})
        record.append_row("a", {"loss": 2.0})
        assert record.summary() == {"run_id": "run-42", "cells": ["b", "a"], "rows": 2}
    stored = json.loads((record.path / SUMMARY_NAME).read_text(encoding="utf-8"))
    assert stored == {"run_id": "run-42", "cells": ["b", "a"], "rows": 2}
    assert read_record(record.path).summary() == stored


def test_summary_must_agree_with_rows(tmp_path: Path) -> None:
    """8.4: a stored summary that disagrees with the rows is not a record.

    The untampered read runs first, so the refusal below is caused by the
    tampering rather than by `read_record` refusing everything.
    """
    with open_record(tmp_path / "record", a_provenance("run-42")) as record:
        record.append_row("only", {"loss": 1.0})
    assert read_record(record.path).summary()["rows"] == 1

    summary = record.path / SUMMARY_NAME
    for tampered in (
        {"run_id": "run-42", "cells": ["only"], "rows": 3},
        {"run_id": "run-42", "cells": ["only", "invented"], "rows": 1},
        {"run_id": "another-run", "cells": ["only"], "rows": 1},
    ):
        summary.write_text(json.dumps(tampered), encoding="utf-8")
        with pytest.raises(ValueError, match="summary"):
            read_record(record.path)


def test_a_summary_document_of_the_wrong_shape_is_refused(tmp_path: Path) -> None:
    """A member 8.4 does not define, or one it does and that is missing."""
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("only", {"loss": 1.0})
    summary = record.path / SUMMARY_NAME
    summary.write_text(
        json.dumps({"run_id": "run-0001", "cells": ["only"], "rows": 1, "when": "now"}),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        read_record(record.path)
    summary.write_text(json.dumps({"run_id": "run-0001", "cells": ["only"]}), encoding="utf-8")
    with pytest.raises(ValidationError):
        read_record(record.path)
    # 8.4's table gives `rows` as an integer, and a reader that accepted the
    # string "1" would accept a record a conforming reader in another language
    # refuses -- the laxness spec 3.2 already rules out for money amounts.
    for wrong_type in ({"rows": "1"}, {"rows": 1.0}, {"cells": "only"}, {"run_id": 1}):
        document = {"run_id": "run-0001", "cells": ["only"], "rows": 1, **wrong_type}
        summary.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ValidationError):
            read_record(record.path)


def test_an_unfinished_record_reads_its_rows_and_says_it_is_unfinished(tmp_path: Path) -> None:
    """8.4: no summary means unfinished, not invalid."""
    record = open_record(tmp_path / "record", a_provenance())
    record.append_row("only", {"loss": 1.0})
    read_back = read_record(record.path)
    assert not read_back.complete
    assert [row.cell for row in read_back.rows] == ["only"]
    assert read_back.summary() == {"run_id": "run-0001", "cells": ["only"], "rows": 1}
    record.close()
    assert read_record(record.path).complete


def test_a_run_that_fails_leaves_its_record_unfinished(tmp_path: Path) -> None:
    """8.4: a run that ends by failing has not finished, so no summary is written."""
    with pytest.raises(ZeroDivisionError), open_record(tmp_path / "record", a_provenance()) as rec:
        rec.append_row("first", {"loss": 1.0})
        raise ZeroDivisionError
    assert not (tmp_path / "record" / SUMMARY_NAME).exists()
    assert [row.cell for row in read_record(tmp_path / "record").rows] == ["first"]


# --- 8.5: a record that cannot be written is a failed run ----------------------


def assert_raises_without_warning(
    expected: type[Exception], call: Callable[[], object]
) -> Exception:
    """`call` must raise `expected` and must warn about nothing on the way.

    Both halves matter. `filterwarnings = ["error"]` would turn a
    `warnings.warn` into an exception, so a check that only asserted "something
    was raised" would pass against an implementation that warned and carried
    on. `simplefilter("always")` makes a warning harmless for the duration,
    which is what lets the two outcomes be told apart.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(expected) as exc:
            call()
    assert [str(w.message) for w in caught] == [], "8.5 forbids warning and continuing"
    return exc.value


def test_unwritable_record_directory_raises_rather_than_warning(tmp_path: Path) -> None:
    """Review Focus 4, and 8.5: the record cannot be written, so the run fails.

    The unwritability is established by trying to write, not by trusting the
    `chmod`: running as root, or on a filesystem that does not enforce the
    mode, the probe succeeds and this test skips rather than passing while
    proving nothing.
    """
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        try:
            (locked / "probe").touch()
        except OSError:
            pass
        else:
            pytest.skip("this process can write into a mode 0o500 directory")
        error = assert_raises_without_warning(
            RecordError, lambda: open_record(locked / "record", a_provenance())
        )
        assert getattr(error, "code", None) == LAB_424
        assert not (locked / "record").exists()
    finally:
        locked.chmod(0o700)


def test_a_record_directory_that_cannot_be_created_raises(tmp_path: Path) -> None:
    """The same refusal, built without depending on filesystem permissions.

    A regular file where the record directory should go is unwritable on every
    platform and for every user, root included, so this test carries the
    contract where the `chmod` one can only skip.
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory\n", encoding="utf-8")
    error = assert_raises_without_warning(
        RecordError, lambda: open_record(blocker / "record", a_provenance())
    )
    assert getattr(error, "code", None) == LAB_424


def unwritable(directory: Path, name: str) -> Path:
    """Make `directory / name` a path that cannot be opened for writing, for anyone.

    A symlink to a path *inside* a regular file: opening it fails with
    `ENOTDIR` on every POSIX platform and for every user, root included, so
    this condition is built rather than borrowed from the ambient filesystem
    the way a `chmod` has to be. `Path.exists()` follows the link and reports
    `False`, which is what the record under test is told before it tries to
    write.
    """
    blocker = directory.parent / "blocker"
    blocker.write_text("not a directory\n", encoding="utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.symlink_to(blocker / "nowhere")
    assert not target.exists(), "the fixture is meant to look absent"
    with pytest.raises(OSError):
        target.open("w", encoding="utf-8")
    return target


def test_a_provenance_record_that_cannot_be_written_raises_rather_than_warning(
    tmp_path: Path,
) -> None:
    """8.5 at the document-write path, which the directory tests never reach.

    The two tests above fail at `mkdir`, so an implementation that warned and
    carried on when a *document* could not be written would pass them both.
    This one, and the two after it, are the three writes section 8.3 names.
    """
    directory = tmp_path / "record"
    unwritable(directory, PROVENANCE_NAME)
    error = assert_raises_without_warning(
        RecordError, lambda: open_record(directory, a_provenance())
    )
    assert getattr(error, "code", None) == LAB_424


def test_a_rows_file_that_cannot_be_opened_raises_rather_than_warning(tmp_path: Path) -> None:
    directory = tmp_path / "record"
    unwritable(directory, ROWS_NAME)
    error = assert_raises_without_warning(
        RecordError, lambda: open_record(directory, a_provenance())
    )
    assert getattr(error, "code", None) == LAB_424


def test_a_summary_that_cannot_be_written_raises_rather_than_warning(tmp_path: Path) -> None:
    """8.5 again: the run reached its end and still has no citable record."""
    directory = tmp_path / "record"
    unwritable(directory, SUMMARY_NAME)
    record = open_record(directory, a_provenance())
    record.append_row("first", {"loss": 1.0})
    error = assert_raises_without_warning(RecordError, record.close)
    assert getattr(error, "code", None) == LAB_424
    assert not record.complete, "8.4: nothing was summarised, so nothing is finished"


class FailingHandle:
    """A rows file whose final flush fails, which is the one write `close` does."""

    def close(self) -> None:
        raise OSError(5, "Input/output error")


def substitute_a_failing_handle(record: RunRecord) -> None:
    """Close the record's real handle and leave one that cannot be closed.

    The real handle is closed first rather than dropped, so no `ResourceWarning`
    reaches a suite that turns warnings into errors.
    """
    real = record._handle
    assert real is not None
    real.close()
    record._handle = FailingHandle()  # type: ignore[assignment]


def test_a_rows_file_that_cannot_be_closed_raises_rather_than_warning(tmp_path: Path) -> None:
    """8.5: closing flushes, so a failure to close is a failure to write."""
    record = open_record(tmp_path / "record", a_provenance())
    record.append_row("first", {"loss": 1.0})
    substitute_a_failing_handle(record)
    error = assert_raises_without_warning(RecordError, record.close)
    assert getattr(error, "code", None) == LAB_424
    assert not record.complete
    assert not (record.path / SUMMARY_NAME).exists()


def test_a_failure_to_close_a_failed_run_is_raised_and_keeps_the_original(
    tmp_path: Path,
) -> None:
    """8.5 even while a run is already leaving by an exception.

    The record failure replaces the experiment's error, and nothing is lost:
    the chain is the `RecordError`, the `OSError` it was raised from, and under
    that the `ZeroDivisionError` that was in flight when the record failed. A
    record that could not be written must not be the quiet half of that pair.
    """
    record = open_record(tmp_path / "record", a_provenance())
    record.append_row("first", {"loss": 1.0})
    substitute_a_failing_handle(record)
    with pytest.raises(RecordError) as exc, record:
        raise ZeroDivisionError
    cause = exc.value.__cause__
    assert isinstance(cause, OSError), cause
    assert isinstance(cause.__context__, ZeroDivisionError), cause.__context__
    assert not (record.path / SUMMARY_NAME).exists()


def test_a_write_failure_mid_run_raises_and_keeps_no_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """8.5: the row is not reported as recorded, because the record lacks it."""
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("first", {"loss": 1.0})

        def fails(handle: TextIO, text: str) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(record_module, "_write_durably", fails)
        error = assert_raises_without_warning(
            RecordError, lambda: record.append_row("second", {"loss": 0.5})
        )
        assert getattr(error, "code", None) == LAB_424
        assert [row.cell for row in record.rows] == ["first"]
        monkeypatch.undo()


def test_a_record_that_is_not_there_is_refused(tmp_path: Path) -> None:
    """8.5 read-side, and the one place HEPH-LAB-424's own words fit exactly."""
    (tmp_path / "file-not-a-directory").write_text("x", encoding="utf-8")
    for path in (tmp_path / "no-such-record", tmp_path / "file-not-a-directory"):
        error = assert_raises_without_warning(RecordError, lambda p=path: read_record(p))
        assert getattr(error, "code", None) == LAB_424

    # A directory missing either document is not a record either.
    for missing in (PROVENANCE_NAME, ROWS_NAME):
        with open_record(tmp_path / missing, a_provenance()) as record:
            record.append_row("only", {"loss": 1.0})
        (record.path / missing).unlink()
        error = assert_raises_without_warning(RecordError, lambda p=record.path: read_record(p))
        assert getattr(error, "code", None) == LAB_424


def test_opening_a_record_where_one_already_exists_is_refused(tmp_path: Path) -> None:
    """8.3: a record is not rewritten, so a second run gets its own directory."""
    with open_record(tmp_path / "record", a_provenance()):
        pass
    with pytest.raises(FileExistsError):
        open_record(tmp_path / "record", a_provenance())


def test_appending_to_a_closed_record_is_refused(tmp_path: Path) -> None:
    record = open_record(tmp_path / "record", a_provenance())
    record.close()
    with pytest.raises(ValueError, match="closed"):
        record.append_row("too-late", {"loss": 1.0})
    with pytest.raises(ValueError, match="closed"):
        read_record(record.path).append_row("too-late", {"loss": 1.0})


# --- 8.2: what a row may carry -------------------------------------------------


def test_a_non_finite_value_is_recorded_as_the_object_8_2_defines(tmp_path: Path) -> None:
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("diverged", {"loss": math.nan, "up": math.inf, "down": -math.inf})
    assert rows_on_disk(record.path) == [
        {
            "cell": "diverged",
            "values": {
                "loss": {"nonfinite": "NaN"},
                "up": {"nonfinite": "Infinity"},
                "down": {"nonfinite": "-Infinity"},
            },
        }
    ]
    values = read_record(record.path).rows[0].values
    assert math.isnan(values["loss"])  # type: ignore[arg-type]
    assert values["up"] == math.inf
    assert values["down"] == -math.inf


def test_a_bare_non_finite_token_in_a_record_is_refused(tmp_path: Path) -> None:
    """8.2: `NaN` is not JSON, so a record holding one is not read as a record."""
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("ok", {"loss": 1.0})
    (record.path / ROWS_NAME).write_text(
        '{"cell":"diverged","values":{"loss":NaN}}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="NaN"):
        read_record(record.path)


def test_a_row_value_that_is_neither_a_number_nor_a_string_is_refused(tmp_path: Path) -> None:
    with open_record(tmp_path / "record", a_provenance()) as record:
        with pytest.raises(ValidationError):
            record.append_row("bad", {"loss": None})  # type: ignore[dict-item]
        with pytest.raises(ValidationError):
            record.append_row("bad", {"loss": [1.0]})  # type: ignore[dict-item]
        # A boolean is a number in Python and is neither in JSON. Pydantic
        # would coerce `True` to 1.0, which is a plausible wrong number in a
        # published record, so it is refused before validation gets the chance.
        with pytest.raises(ValueError, match="boolean"):
            record.append_row("bad", {"flag": True})  # type: ignore[dict-item]
        assert record.rows == ()


def test_values_are_read_back_as_the_mapping_the_row_was_given(tmp_path: Path) -> None:
    """A row's numbers survive the round trip, including an integral float."""
    given: Mapping[str, float | str] = {"loss": 1.0, "acc": 0.9375, "name": "resnet"}
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("cell-a", given)
    assert read_record(record.path).rows[0].values == dict(given)


def test_an_empty_cell_name_is_refused(tmp_path: Path) -> None:
    with open_record(tmp_path / "record", a_provenance()) as record, pytest.raises(ValidationError):
        record.append_row("", {"loss": 1.0})


def test_a_duplicate_cell_is_refused(tmp_path: Path) -> None:
    """8.2: a record that named one cell twice could not say what the run produced."""
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("cell-a", {"loss": 1.0})
        with pytest.raises(ValueError, match="cell-a"):
            record.append_row("cell-a", {"loss": 2.0})
        assert [row.cell for row in record.rows] == ["cell-a"]
    assert len(rows_on_disk(record.path)) == 1


def test_a_record_holding_a_duplicate_cell_is_not_read_back(tmp_path: Path) -> None:
    """8.2 on the read side, which is a different branch from the append side.

    Two details are what make this able to fail for its own reason, and it
    could not before. The summary is removed, because otherwise the derived
    summary of two rows disagrees with the stored one and `read_record` refuses
    at the 8.4 check instead -- with a message that interpolates the stored
    document and therefore matches `cell-a` anyway. And the match is on
    `repeats`, the word only the duplicate-cell refusal uses, so an unrelated
    refusal cannot satisfy it.
    """
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("cell-a", {"loss": 1.0})
    (record.path / ROWS_NAME).write_text(
        '{"cell":"cell-a","values":{}}\n{"cell":"cell-a","values":{}}\n', encoding="utf-8"
    )
    (record.path / SUMMARY_NAME).unlink()
    with pytest.raises(ValueError, match="repeats"):
        read_record(record.path)


def test_the_row_in_flight_when_the_writer_died_is_the_only_one_lost(tmp_path: Path) -> None:
    """8.3: a final line with no LF was never a complete row, so it is discarded.

    This is the one row a crash is allowed to cost. Without the rule a record
    torn mid-write would be unreadable, which would cost the run every cell
    that did complete -- the opposite of what 8.3 is for.
    """
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("first", {"loss": 1.0})
    rows = record.path / ROWS_NAME
    rows.write_text(rows.read_text(encoding="utf-8") + '{"cell":"torn","valu', encoding="utf-8")
    (record.path / SUMMARY_NAME).unlink()
    assert [row.cell for row in read_record(record.path).rows] == ["first"]


def test_a_torn_line_that_is_not_the_last_is_refused(tmp_path: Path) -> None:
    """8.3: only the final line may be incomplete; anything else is corruption.

    An LF-terminated line that is not a row document means the file was
    corrupted or edited, and reading past it would report a run whose rows
    nobody can account for.
    """
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("first", {"loss": 1.0})
    rows = record.path / ROWS_NAME
    rows.write_text('{"cell":"torn","valu\n' + rows.read_text(encoding="utf-8"), encoding="utf-8")
    (record.path / SUMMARY_NAME).unlink()
    with pytest.raises(ValueError):
        read_record(record.path)


def test_a_row_document_of_the_wrong_shape_is_refused(tmp_path: Path) -> None:
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("ok", {"loss": 1.0})
    (record.path / ROWS_NAME).write_text(
        '{"cell":"ok","values":{},"when":"now"}\n', encoding="utf-8"
    )
    with pytest.raises(ValidationError):
        read_record(record.path)


def test_an_object_that_is_not_8_2_s_wrapper_is_refused(tmp_path: Path) -> None:
    """8.2: the wrapper is the one object a value may be, with one spelling."""
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("ok", {"loss": 1.0})
    rows = record.path / ROWS_NAME
    for bad in ('{"nonfinite":"nope"}', '{"nonfinite":"NaN","extra":1}', '{"mean":1}'):
        rows.write_text(f'{{"cell":"c","values":{{"loss":{bad}}}}}\n', encoding="utf-8")
        (record.path / SUMMARY_NAME).unlink(missing_ok=True)
        with pytest.raises(ValueError, match="8.2"):
            read_record(record.path)


def test_a_document_of_a_record_that_is_not_a_json_object_is_refused(tmp_path: Path) -> None:
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("ok", {"loss": 1.0})
    (record.path / PROVENANCE_NAME).write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        read_record(record.path)
    (record.path / PROVENANCE_NAME).write_text(
        json.dumps(a_provenance().as_document()), encoding="utf-8"
    )
    (record.path / ROWS_NAME).write_text('"a string, not a row"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        read_record(record.path)


def test_an_empty_line_in_the_rows_file_is_refused(tmp_path: Path) -> None:
    """8.1: each line of `rows.jsonl` is one row and holds nothing else."""
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("ok", {"loss": 1.0})
    rows = record.path / ROWS_NAME
    rows.write_text("\n" + rows.read_text(encoding="utf-8"), encoding="utf-8")
    (record.path / SUMMARY_NAME).unlink()
    with pytest.raises(ValueError, match="is empty"):
        read_record(record.path)


def test_a_row_whose_values_member_is_not_an_object_is_refused(tmp_path: Path) -> None:
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("ok", {"loss": 1.0})
    (record.path / ROWS_NAME).write_text('{"cell":"c","values":5}\n', encoding="utf-8")
    (record.path / SUMMARY_NAME).unlink()
    with pytest.raises(ValidationError):
        read_record(record.path)


def test_a_record_document_that_cannot_be_read_at_all_is_refused(tmp_path: Path) -> None:
    """Not every unreadable document is an absent one, and both are no record.

    A directory where a document belongs is unreadable for every user, root
    included, so this builds the condition rather than borrowing it from the
    ambient filesystem.
    """
    for unreadable_name in (PROVENANCE_NAME, ROWS_NAME):
        directory = tmp_path / f"record-{unreadable_name}"
        directory.mkdir()
        for name in (PROVENANCE_NAME, ROWS_NAME):
            if name == unreadable_name:
                (directory / name).mkdir()
            elif name == PROVENANCE_NAME:
                (directory / name).write_text(
                    json.dumps(a_provenance().as_document()), encoding="utf-8"
                )
            else:
                (directory / name).write_text("", encoding="utf-8")
        error = assert_raises_without_warning(RecordError, lambda d=directory: read_record(d))
        assert getattr(error, "code", None) == LAB_424


def test_a_record_carries_the_provenance_it_was_opened_with(tmp_path: Path) -> None:
    """8.1: stored unchanged, so what is read back is what was handed in."""
    provenance = a_provenance("run-provenance")
    with open_record(tmp_path / "record", provenance) as record:
        assert record.provenance == provenance
    assert read_record(record.path).provenance == provenance


def test_closing_a_record_twice_is_harmless(tmp_path: Path) -> None:
    """A record closed by its context manager may be closed again."""
    record = open_record(tmp_path / "record", a_provenance())
    record.close()
    assert record.complete
    record.close()
    assert record.complete
    assert len(json.loads((record.path / SUMMARY_NAME).read_text(encoding="utf-8"))) == 3


def test_a_record_read_back_may_be_used_as_a_context_manager(tmp_path: Path) -> None:
    """It has nothing open, so leaving it -- by an exception or not -- writes nothing."""
    with open_record(tmp_path / "record", a_provenance()) as record:
        record.append_row("only", {"loss": 1.0})
    read_back = read_record(record.path)
    # A sentinel, appended after the read: an identical rewrite would drop it,
    # so "wrote nothing" and "wrote the same bytes again" are told apart. Byte
    # equality alone cannot do that.
    summary = record.path / SUMMARY_NAME
    sentinel = "\nnothing may rewrite this file"
    summary.write_text(summary.read_text(encoding="utf-8") + sentinel, encoding="utf-8")
    with pytest.raises(ZeroDivisionError), read_back:
        raise ZeroDivisionError
    with read_back:
        pass
    text = summary.read_text(encoding="utf-8")
    assert text.endswith(sentinel), "the summary was rewritten"
    assert json.loads(text[: -len(sentinel)]) == {
        "run_id": "run-0001",
        "cells": ["only"],
        "rows": 1,
    }


# --- 8.6: the registry ---------------------------------------------------------


def test_registered_experiment_cannot_choose_its_output_path(
    tmp_path: Path, clean_registry: None
) -> None:
    """8.6: the experiment is handed the record; the runner chose where it went.

    Two claims, and the test asserts both. The experiment receives the very
    record object the runner opened -- recorded by the experiment rather than
    inferred from the filesystem -- and its signature has one parameter, so
    there is no argument through which a destination could have reached it.

    "Cannot choose" is the brief's name for the contract and is read in those
    terms: no destination reaches the experiment through its signature. It is
    not the stronger claim that an experiment cannot write a file at all --
    `RunRecord.path` is public, and no library in this language could enforce
    that. The test asserts the claim that is true.
    """
    received: list[RunRecord] = []

    @register("one-cell")
    def experiment(record: RunRecord) -> None:
        received.append(record)
        record.append_row("cell-a", {"loss": 1.5})

    assert list(inspect.signature(experiment).parameters) == ["record"]

    directory = tmp_path / "chosen-by-the-runner"
    finished = run("one-cell", directory, provenance=a_provenance("run-registry"))
    assert received == [finished]
    assert finished.path == directory
    assert finished.summary() == {"run_id": "run-registry", "cells": ["cell-a"], "rows": 1}


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param(lambda record, directory: None, id="a-second-positional"),
        pytest.param(lambda record, directory=None: None, id="a-defaulted-destination"),
        pytest.param(lambda *args: None, id="star-args"),
        pytest.param(lambda **kwargs: None, id="star-kwargs"),
        pytest.param(lambda: None, id="no-record-at-all"),
        pytest.param(lambda *, record=None: None, id="keyword-only"),
    ],
)
def test_registration_refuses_an_experiment_that_could_be_handed_a_destination(
    candidate: Callable[..., None], clean_registry: None
) -> None:
    """8.6: refused at registration, not discovered when the function runs."""
    with pytest.raises(TypeError):
        register("refused")(candidate)
    assert "refused" not in registered()


def test_running_an_unregistered_name_is_refused(tmp_path: Path, clean_registry: None) -> None:
    with pytest.raises(KeyError, match="nobody-registered-this"):
        run("nobody-registered-this", tmp_path / "record", provenance=a_provenance())


def test_a_second_experiment_may_not_take_a_registered_name(clean_registry: None) -> None:
    register("taken")(lambda record: None)
    with pytest.raises(ValueError, match="taken"):
        register("taken")(lambda record: None)


def test_an_experiment_that_raises_leaves_an_unfinished_record(
    tmp_path: Path, clean_registry: None
) -> None:
    """8.5 again, from the runner: nothing here swallows the experiment's failure."""

    @register("fails-after-a-cell")
    def experiment(record: RunRecord) -> None:
        record.append_row("cell-a", {"loss": 1.5})
        raise RuntimeError("the experiment failed")

    with pytest.raises(RuntimeError, match="the experiment failed"):
        run("fails-after-a-cell", tmp_path / "record", provenance=a_provenance())
    assert not (tmp_path / "record" / SUMMARY_NAME).exists()
    assert [row.cell for row in read_record(tmp_path / "record").rows] == ["cell-a"]


def test_the_registry_view_is_a_copy(clean_registry: None) -> None:
    """`registered()` hands out no handle on the registry itself."""
    registered()["smuggled"] = lambda record: None
    assert "smuggled" not in registered()


def test_os_fsync_is_what_makes_a_row_durable(monkeypatch: pytest.MonkeyPatch) -> None:
    """8.3: the row is flushed out of the process buffer and synced to storage.

    Asserted by recording what the write handed to the operating system rather
    than by timing anything: a flush with no fsync leaves the bytes in the page
    cache, which survives this process but not the machine, and 8.3 asks for
    both.
    """
    calls: list[str] = []

    class Handle:
        def write(self, text: str) -> int:
            calls.append(f"write:{text.strip()}")
            return len(text)

        def flush(self) -> None:
            calls.append("flush")

        def fileno(self) -> int:
            return 4242

    monkeypatch.setattr(os, "fsync", lambda fd: calls.append(f"fsync:{fd}"))
    record_module._write_durably(Handle(), "a line\n")  # type: ignore[arg-type]
    assert calls == ["write:a line", "flush", "fsync:4242"]
