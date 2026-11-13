"""Replay and diff: what is compared, and what the report says (spec section 9).

`conformance/lab/diff.json` drives the comparison itself through
`test_conformance.py`, so this file covers what a vector cannot: a real
re-execution of a registered experiment against a record on disk, and the
clauses whose content is an *absence* -- `environment`, `run_id` and `class`
are not compared, and a divergence is reported rather than raised.

Two habits make those checkable rather than claimed.

**An absence is paired with the implementation that would break it.**
:data:`~hephkit.lab.replay.COMPARED_MEMBERS` is the single place that decides
which members of the provenance record a replay compares, so a test can add a
member to it and show that the same records which match now report a
difference. Without that, "`environment` is not compared" is a test that passes
against an implementation comparing nothing at all.

**NaN is compared against the implementation 9.3 forbids.**
:func:`naive_match` is `==`, which is what an implementation reaches for and
what IEEE 754 makes wrong, and the NaN tests assert that it gives the opposite
answer on the same input.
"""

from __future__ import annotations

import math
import socket
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from hephkit.errors import LAB_409, LAB_424, HephError
from hephkit.lab import record as record_module
from hephkit.lab import replay as replay_module
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
from hephkit.lab.replay import (
    ABSOLUTE_TOLERANCE,
    COMPARED_MEMBERS,
    RELATIVE_TOLERANCE,
    Difference,
    DiffReport,
    ReplayError,
    compare,
    members_match,
    replay,
    values_match,
)
from hephkit.lab.repro import ProvenanceRecord
from pydantic import ValidationError

# Content hashes (spec 4.2) quoted from `conformance/hashing/content.json`
# (`empty-object`, `null`, `empty-string`, `key-order-does-not-change-hash`), so
# no hash string in this file is of unknown origin.
CONFIG_HASH = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
DATA_HASH = "sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"
OTHER_HASH = "sha256:12ae32cb1ec02d01eda3581b127c1fee3b0dc53572ed6baf239721a03d82e126"
DEPS_HASH = "sha256:d3626ac30a87e6f7a6428233b3c68299976865fa5508e4267c5415c76af7a772"

# Synthetic commit SHAs, 40 lowercase hex, as `conformance/lab/provenance.json` uses.
CODE_SHA = "c0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ff"
OTHER_SHA = "dec0dedec0dedec0dedec0dedec0dedec0dedec0"

ENVIRONMENT = {
    "platform": "macOS-15.6-arm64",
    "python": "3.12.7",
    "frameworks": {"numpy": "2.1.3", "torch": None},
    "accelerator": None,
}
OTHER_ENVIRONMENT = {
    "platform": "Linux-6.8.0-x86_64",
    "python": "3.13.1",
    "frameworks": {"numpy": "2.2.0", "torch": "2.6.0"},
    "accelerator": {"model": "NVIDIA RTX 4090", "driver": "550.54.14"},
}

#: What the fixture experiment reports. A dict rather than a literal so a test
#: can perturb the value the re-execution sees, which is the stand-in for an
#: input that moved; freezing inputs is a later module.
INPUTS: dict[str, float] = {"loss": 0.5}


def a_provenance(
    run_id: str = "run-0001",
    *,
    config_hash: str = CONFIG_HASH,
    data_hash: str = DATA_HASH,
    deps_hash: str | None = DEPS_HASH,
    code_sha: str | None = CODE_SHA,
    run_class: str = "deterministic",
    environment: Mapping[str, Any] = ENVIRONMENT,
) -> ProvenanceRecord:
    """A section 7 record, built by hand rather than captured.

    Hand-built so that every assertion here is about section 9 rather than
    about the machine the suite runs on; `class` is a member name and not a
    Python identifier, so the model is validated from a document.
    """
    return ProvenanceRecord.model_validate(
        {
            "run_id": run_id,
            "config_hash": config_hash,
            "data_hash": data_hash,
            "deps_hash": deps_hash,
            "code_sha": code_sha,
            "class": run_class,
            "environment": dict(environment),
        }
    )


def a_record(
    directory: Path,
    rows: Mapping[str, Mapping[str, float | str]],
    provenance: ProvenanceRecord | None = None,
) -> RunRecord:
    """Write a record at `directory` and read it back, as a replay would."""
    with open_record(directory, provenance if provenance is not None else a_provenance()) as new:
        for cell, values in rows.items():
            new.append_row(cell, values)
    return read_record(directory)


def an_unfinished_record(
    directory: Path, rows: Mapping[str, Mapping[str, float | str]]
) -> RunRecord:
    """A record whose run did not reach its end (spec 8.4): rows, and no summary.

    Built the way 8.4 says one comes about -- the run ends by failing, so the
    context manager writes no summary -- rather than by deleting a file
    afterwards, which would be a record somebody edited rather than a run that
    died.
    """
    with pytest.raises(RuntimeError, match="the run died"):
        with open_record(directory, a_provenance()) as record:
            for cell, values in rows.items():
                record.append_row(cell, values)
            raise RuntimeError("the run died")
    read_back = read_record(directory)
    assert not read_back.complete, "8.4: a record with no summary is unfinished"
    return read_back


def naive_match(recorded: float | str, replayed: float | str) -> bool:
    """The comparison spec 9.3 forbids: the language's own equality.

    Used by the NaN tests to show that the same input gets the opposite answer
    from it, so that "NaN matches NaN" is a check with a demonstrated bite
    rather than an assertion about an implementation nobody wrote.
    """
    return recorded == replayed


def null_matches_nothing(recorded: str | None, replayed: str | None) -> bool:
    """The member comparison spec 9.3 forbids: a `null` matches nothing.

    The mistake an implementation makes by reading 9.3's three value kinds as
    exhaustive and treating an absent member as "no value, so no match". Used
    by the `null` test below to show that the same input gets the opposite
    answer from it.
    """
    return recorded is not None and recorded == replayed


@pytest.fixture
def clean_registry() -> Iterator[None]:
    """Leave the process-wide experiment registry as it was found."""
    saved = dict(registered())
    try:
        yield
    finally:
        record_module._EXPERIMENTS.clear()
        record_module._EXPERIMENTS.update(saved)


@pytest.fixture
def clean_inputs() -> Iterator[None]:
    """Restore :data:`INPUTS` so a perturbation does not leak into later tests."""
    saved = dict(INPUTS)
    try:
        yield
    finally:
        INPUTS.clear()
        INPUTS.update(saved)


@pytest.fixture
def fixture_experiment(clean_registry: None) -> str:
    """Register an experiment that reports what :data:`INPUTS` says."""

    name = "replay-fixture"

    @register(name)
    def experiment(record: RunRecord) -> None:
        record.append_row("cell-a", {"loss": INPUTS["loss"], "note": "converged"})
        record.append_row("cell-b", {"loss": INPUTS["loss"] * 2})

    return name


def a_recorded_run(tmp_path: Path, experiment: str) -> Path:
    """Record one run of `experiment`, and return the record directory."""
    directory = tmp_path / "recorded"
    run(experiment, directory, provenance=a_provenance())
    return directory


@pytest.fixture
def raising_experiment(clean_registry: None) -> str:
    """Register an experiment that records a cell and then fails."""

    name = "replay-raising-fixture"

    @register(name)
    def experiment(record: RunRecord) -> None:
        record.append_row("cell-a", {"loss": 0.5})
        raise RuntimeError("the experiment failed")

    return name


@pytest.fixture
def unsorted_experiment(clean_registry: None) -> str:
    """Register an experiment whose values are produced out of canonical order.

    `INPUTS["extra"]` decides whether the cell carries any value at all, so a
    replay can hold two positions the record does not -- in the order the run
    produced them, which is not the order 4.1 sorts them into.
    """

    name = "replay-unsorted-fixture"

    @register(name)
    def experiment(record: RunRecord) -> None:
        values: dict[str, float | str] = {}
        if INPUTS.get("extra"):
            values = {"zeta": 1.0, "alpha": 2.0}
        record.append_row("cell-a", values)

    return name


# --- 9.1: a replay re-executes a recorded run and compares it ------------------


def test_identical_run_replays_and_matches(tmp_path: Path, fixture_experiment: str) -> None:
    recorded = a_recorded_run(tmp_path, fixture_experiment)
    report = replay(
        recorded,
        experiment=fixture_experiment,
        into=tmp_path / "replayed",
        provenance=a_provenance("run-0002"),
    )
    assert report.matched
    assert report.differences == ()


def test_perturbed_input_names_the_changed_value(
    tmp_path: Path, fixture_experiment: str, clean_inputs: None
) -> None:
    """Design 9.3's contract test: a perturbed input produces a diff naming it."""
    recorded = a_recorded_run(tmp_path, fixture_experiment)
    INPUTS["loss"] = 0.25
    report = replay(
        recorded,
        experiment=fixture_experiment,
        into=tmp_path / "replayed",
        provenance=a_provenance("run-0002"),
    )
    assert not report.matched
    assert [d.as_document() for d in report.differences] == [
        {"cell": "cell-a", "key": "loss", "recorded": 0.5, "replayed": 0.25},
        {"cell": "cell-b", "key": "loss", "recorded": 1.0, "replayed": 0.5},
    ], "the report names each cell and key that moved, and nothing that did not"


def test_environment_difference_does_not_break_a_match(
    tmp_path: Path, fixture_experiment: str
) -> None:
    """7.2 and 9.1, on the replay path rather than on `compare` directly.

    A re-execution on a second machine carries a different `environment`, and
    that is the case 7.2 says must still be the same run.
    """
    recorded = a_recorded_run(tmp_path, fixture_experiment)
    report = replay(
        recorded,
        experiment=fixture_experiment,
        into=tmp_path / "replayed",
        provenance=a_provenance("run-0002", environment=OTHER_ENVIRONMENT),
    )
    assert report.matched


def test_a_divergence_is_reported_and_not_raised(
    tmp_path: Path, fixture_experiment: str, clean_inputs: None
) -> None:
    """9.1: an implementation MUST NOT refuse in place of producing the report."""
    recorded = a_recorded_run(tmp_path, fixture_experiment)
    INPUTS["loss"] = 0.25
    report = replay(
        recorded,
        experiment=fixture_experiment,
        into=tmp_path / "replayed",
        provenance=a_provenance("run-0002"),
    )
    assert isinstance(report, DiffReport)
    assert not report.matched


def test_replay_with_network_blocked_still_matches(
    tmp_path: Path, fixture_experiment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Design 9.3's contract test: a recorded run replays with the network blocked."""
    recorded = a_recorded_run(tmp_path, fixture_experiment)

    def no_network(*args: object, **kwargs: object) -> socket.socket:
        raise OSError("the network is blocked for this test")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    with pytest.raises(OSError, match="blocked"):
        socket.socket()
    report = replay(
        recorded,
        experiment=fixture_experiment,
        into=tmp_path / "replayed",
        provenance=a_provenance("run-0002"),
    )
    assert report.matched


def test_the_replay_writes_a_record_of_its_own(tmp_path: Path, fixture_experiment: str) -> None:
    """8.1 holds for the re-execution too: it is a run, so it leaves a record."""
    recorded = a_recorded_run(tmp_path, fixture_experiment)
    into = tmp_path / "replayed"
    replay(
        recorded,
        experiment=fixture_experiment,
        into=into,
        provenance=a_provenance("run-0002"),
    )
    assert sorted(p.name for p in into.iterdir()) == sorted(
        [PROVENANCE_NAME, ROWS_NAME, SUMMARY_NAME]
    )


def test_the_re_execution_is_compared_as_it_was_written(
    tmp_path: Path, unsorted_experiment: str, clean_inputs: None
) -> None:
    """9.2's order holds for the re-execution's rows, not only the record's.

    The experiment produces `zeta` before `alpha`, so the live record object
    `lab.record.run` returns holds them in that order while the file holds
    them in 4.1's. A replay that compared the live object would report the
    pair the other way round, and two readers of the same two records would
    disagree about the order of one report.
    """
    recorded = a_recorded_run(tmp_path, unsorted_experiment)
    INPUTS["extra"] = 1.0
    report = replay(
        recorded,
        experiment=unsorted_experiment,
        into=tmp_path / "replayed",
        provenance=a_provenance("run-0002"),
    )
    assert [d.as_document() for d in report.differences] == [
        {"cell": "cell-a", "key": "alpha", "recorded": None, "replayed": 2.0},
        {"cell": "cell-a", "key": "zeta", "recorded": None, "replayed": 1.0},
    ]


def test_a_re_execution_whose_experiment_raises_produces_no_report(
    tmp_path: Path, fixture_experiment: str, raising_experiment: str
) -> None:
    """9.1: the failure reaches the caller, and the partial record stays put.

    The forbidden alternatives are a report that calls the cells the
    re-execution never reached a divergence, and discarding the partial record
    -- which is the thing that says how far it got (8.4, 8.5).
    """
    recorded = a_recorded_run(tmp_path, fixture_experiment)
    into = tmp_path / "replayed"
    with pytest.raises(RuntimeError, match="the experiment failed"):
        replay(
            recorded,
            experiment=raising_experiment,
            into=into,
            provenance=a_provenance("run-0002"),
        )
    left_behind = read_record(into)
    assert not left_behind.complete, "8.4: a run that ends by failing has not finished"
    assert [row.cell for row in left_behind.rows] == ["cell-a"], (
        "the rows the re-execution reached are still there (8.3)"
    )


def test_the_replays_provenance_is_the_callers_and_not_the_records(
    tmp_path: Path, fixture_experiment: str
) -> None:
    """The re-execution's provenance must not be copied from the record.

    If it were, `config_hash`, `data_hash`, `deps_hash` and `code_sha` would be
    equal by construction and four of the five things 9.1 compares could never
    differ -- a check that cannot fail. The replay is handed a provenance whose
    `config_hash` differs, and the report must say so.
    """
    recorded = a_recorded_run(tmp_path, fixture_experiment)
    report = replay(
        recorded,
        experiment=fixture_experiment,
        into=tmp_path / "replayed",
        provenance=a_provenance("run-0002", config_hash=OTHER_HASH),
    )
    assert not report.matched
    assert [d.as_document() for d in report.differences] == [
        {"cell": None, "key": "config_hash", "recorded": CONFIG_HASH, "replayed": OTHER_HASH}
    ]


def test_a_record_that_is_not_there_is_a_record_error_not_a_replay_error(
    tmp_path: Path, fixture_experiment: str
) -> None:
    """424 is for an artefact that is not there; 409 is for a divergence.

    A replay does not re-wrap `lab.record`'s refusal: the record of the run
    being replayed is 424's own example, and a second code for it would make
    the registry's disambiguation meaningless.
    """
    with pytest.raises(RecordError) as exc:
        replay(
            tmp_path / "absent",
            experiment=fixture_experiment,
            into=tmp_path / "replayed",
            provenance=a_provenance("run-0002"),
        )
    assert exc.value.code == LAB_424
    assert not isinstance(exc.value, ReplayError)
    assert not (tmp_path / "replayed").exists(), "the record is read before anything is run"


def test_an_unregistered_experiment_name_raises_key_error(tmp_path: Path) -> None:
    """Not a replay error either: `lab.record.run` already settled this refusal."""
    recorded = tmp_path / "recorded"
    a_record(recorded, {"cell-a": {"loss": 0.5}})
    with pytest.raises(KeyError, match="no experiment named"):
        replay(
            recorded,
            experiment="never-registered",
            into=tmp_path / "replayed",
            provenance=a_provenance("run-0002"),
        )


# --- 9.1: what is compared, and what is not ------------------------------------


@pytest.mark.parametrize(
    ("member", "other"),
    [
        ("config_hash", OTHER_HASH),
        ("data_hash", OTHER_HASH),
        ("deps_hash", None),
        ("code_sha", None),
    ],
)
def test_each_determinism_contract_member_is_compared(
    tmp_path: Path, member: str, other: str | None
) -> None:
    rows = {"cell-a": {"loss": 0.5}}
    recorded = a_record(tmp_path / "recorded", rows)
    # A record carrying a null `deps_hash` or `code_sha` cannot be
    # `deterministic` (7.3), so the class moves with the member.
    perturbed = {member: other, "run_class": "provenance-only" if other is None else "deterministic"}
    replayed = a_record(
        tmp_path / "replayed", rows, a_provenance("run-0002", **perturbed)  # type: ignore[arg-type]
    )
    report = compare(recorded, replayed)
    assert not report.matched
    assert [d.as_document() for d in report.differences] == [
        {
            "cell": None,
            "key": member,
            "recorded": getattr(recorded.provenance, member),
            "replayed": other,
        }
    ]


def test_a_null_member_equals_a_null_member(tmp_path: Path) -> None:
    """9.3: a `null` is a fourth kind and equals a `null` and nothing else.

    7.3 makes a `null` `deps_hash` and a `null` `code_sha` exactly what a
    `provenance-only` run carries, so this is every replay of the ordinary
    case rather than an exotic one.
    """
    rows = {"cell-a": {"loss": 0.5}}
    unpinned = a_provenance(deps_hash=None, code_sha=None, run_class="provenance-only")
    recorded = a_record(tmp_path / "recorded", rows, unpinned)
    replayed = a_record(tmp_path / "replayed", rows, unpinned)
    assert recorded.provenance.deps_hash is None
    assert recorded.provenance.code_sha is None
    report = compare(recorded, replayed)
    assert report.matched, "two absences are not a difference"
    assert members_match(None, None) is True


def test_the_null_member_check_fails_against_an_implementation_that_matches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check above biting: the forbidden reading reports a run against itself.

    `null_matches_nothing` is what an implementation writes by taking 9.3's
    three value kinds as exhaustive. Against it the very same two records
    report a difference at both null members -- which is the failure mode 9.3's
    fourth kind exists to stop, and it would hit every `provenance-only` run.
    """
    rows = {"cell-a": {"loss": 0.5}}
    unpinned = a_provenance(deps_hash=None, code_sha=None, run_class="provenance-only")
    recorded = a_record(tmp_path / "recorded", rows, unpinned)
    replayed = a_record(tmp_path / "replayed", rows, unpinned)
    assert compare(recorded, replayed).matched
    assert null_matches_nothing(None, None) is False
    monkeypatch.setattr(replay_module, "members_match", null_matches_nothing)
    report = compare(recorded, replayed)
    assert [d.as_document() for d in report.differences] == [
        {"cell": None, "key": "deps_hash", "recorded": None, "replayed": None},
        {"cell": None, "key": "code_sha", "recorded": None, "replayed": None},
    ]


def test_a_null_member_differs_from_a_present_one() -> None:
    """The other half of 9.3's `null` rule: it equals a `null` and nothing else."""
    assert members_match(DEPS_HASH, DEPS_HASH) is True
    assert members_match(None, DEPS_HASH) is False
    assert members_match(DEPS_HASH, None) is False
    assert members_match(DEPS_HASH, OTHER_HASH) is False


def test_the_compared_members_are_the_determinism_contract_of_7_1() -> None:
    """9.1 names four members, in 7.1's table order, and no others."""
    assert COMPARED_MEMBERS == ("config_hash", "data_hash", "deps_hash", "code_sha")


def test_environment_run_id_and_class_are_not_compared(tmp_path: Path) -> None:
    """9.1: the three members of 7.1 outside the determinism contract."""
    rows = {"cell-a": {"loss": 0.5}}
    recorded = a_record(tmp_path / "recorded", rows, a_provenance("run-0001"))
    replayed = a_record(
        tmp_path / "replayed",
        rows,
        a_provenance("run-0002", run_class="provenance-only", environment=OTHER_ENVIRONMENT),
    )
    assert recorded.provenance.run_id != replayed.provenance.run_id
    assert recorded.provenance.run_class != replayed.provenance.run_class
    assert recorded.provenance.environment != replayed.provenance.environment
    assert compare(recorded, replayed) == DiffReport(
        matched=True, record_unfinished=False, differences=()
    )


def test_adding_a_member_to_the_compared_set_does_produce_a_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check above biting, demonstrated rather than assumed.

    `COMPARED_MEMBERS` is the one place that decides which members a replay
    compares, so adding `run_id` to it must make two records differing only in
    `run_id` report a difference. Without this, the test above would pass
    against an implementation that compared no provenance member at all, and
    the four tests above it would pass against one that compared only the
    four by accident of their own data.
    """
    rows = {"cell-a": {"loss": 0.5}}
    recorded = a_record(tmp_path / "recorded", rows, a_provenance("run-0001"))
    replayed = a_record(tmp_path / "replayed", rows, a_provenance("run-0002"))
    assert compare(recorded, replayed).matched
    monkeypatch.setattr(replay_module, "COMPARED_MEMBERS", (*COMPARED_MEMBERS, "run_id"))
    report = compare(recorded, replayed)
    assert [d.as_document() for d in report.differences] == [
        {"cell": None, "key": "run_id", "recorded": "run-0001", "replayed": "run-0002"}
    ]


def test_the_order_of_the_rows_is_not_compared(tmp_path: Path) -> None:
    """9.1: rows are in completion order, which is not a result."""
    recorded = a_record(tmp_path / "recorded", {"cell-a": {"loss": 0.5}, "cell-b": {"loss": 1.0}})
    replayed = a_record(tmp_path / "replayed", {"cell-b": {"loss": 1.0}, "cell-a": {"loss": 0.5}})
    assert [row.cell for row in recorded.rows] != [row.cell for row in replayed.rows]
    assert compare(recorded, replayed).matched


# --- 9.2: the difference report -----------------------------------------------


def test_a_report_matched_exactly_when_it_carries_no_difference() -> None:
    """9.2: neither a match alongside a difference nor a divergence with none."""
    moved = Difference(cell="cell-a", key="loss", recorded=0.5, replayed=0.25)
    with pytest.raises(ValidationError, match="matched"):
        DiffReport(matched=True, record_unfinished=False, differences=(moved,))
    with pytest.raises(ValidationError, match="matched"):
        DiffReport(matched=False, record_unfinished=False, differences=())
    assert DiffReport(matched=True, record_unfinished=False, differences=()).matched
    assert not DiffReport(matched=False, record_unfinished=False, differences=(moved,)).matched


def test_a_report_says_when_the_record_it_compared_was_unfinished(tmp_path: Path) -> None:
    """9.2: an unfinished record's unreached cells are reported, and flagged as such.

    `cell-b` is in the re-execution and not in the record because the recorded
    run died before reaching it, not because a value appeared. The difference
    stays in the report -- it is a true statement about the two records -- and
    `record_unfinished` is what lets a reader tell the two apart.
    """
    recorded = an_unfinished_record(tmp_path / "recorded", {"cell-a": {"loss": 0.5}})
    replayed = a_record(
        tmp_path / "replayed", {"cell-a": {"loss": 0.5}, "cell-b": {"loss": 0.25}}
    )
    report = compare(recorded, replayed)
    assert report.record_unfinished is True
    assert [d.as_document() for d in report.differences] == [
        {"cell": "cell-b", "key": "loss", "recorded": None, "replayed": 0.25}
    ], "9.2: the unreached cell is reported rather than suppressed"
    assert report.as_document()["record_unfinished"] is True


def test_record_unfinished_is_about_the_recorded_side_only(tmp_path: Path) -> None:
    """Both directions, because the member names one side and not the other.

    Whether the re-execution finished is not a fact about the comparison: 9.1
    says a re-execution that did not finish produces no report at all, so an
    implementation reading `complete` off the replayed side would report
    `false` for the case above and `true` for a case 9.1 never reaches.
    """
    rows: dict[str, dict[str, float | str]] = {"cell-a": {"loss": 0.5}}
    finished = a_record(tmp_path / "finished", rows)
    other_finished = a_record(tmp_path / "other-finished", rows)
    unfinished = an_unfinished_record(tmp_path / "unfinished", rows)
    assert compare(finished, other_finished).record_unfinished is False
    assert compare(unfinished, finished).record_unfinished is True
    assert compare(finished, unfinished).record_unfinished is False


def test_a_cell_only_the_record_holds_names_each_of_its_values(tmp_path: Path) -> None:
    """Each value is named, in the order 9.2 gives: the row's `values` order.

    `grad_norm` before `loss` although the run produced them the other way
    round, because 8.1 makes every document in a record canonical JSON and 4.1
    sorts a row's member names.
    """
    recorded = a_record(
        tmp_path / "recorded",
        {"cell-a": {"loss": 0.5}, "cell-b": {"loss": 0.25, "grad_norm": 1.5}},
    )
    replayed = a_record(tmp_path / "replayed", {"cell-a": {"loss": 0.5}})
    assert [d.as_document() for d in compare(recorded, replayed).differences] == [
        {"cell": "cell-b", "key": "grad_norm", "recorded": 1.5, "replayed": None},
        {"cell": "cell-b", "key": "loss", "recorded": 0.25, "replayed": None},
    ]


def test_a_cell_only_the_replay_holds_names_each_of_its_values(tmp_path: Path) -> None:
    """Two values, so "each" and the within-cell order can both fail.

    With one value this test would pass against an implementation that
    reported only a replay-only cell's first value, or reversed them; its
    record-side twin above has the same shape for the same reason.
    """
    recorded = a_record(tmp_path / "recorded", {"cell-a": {"loss": 0.5}})
    replayed = a_record(
        tmp_path / "replayed",
        {"cell-a": {"loss": 0.5}, "cell-c": {"loss": 0.75, "grad_norm": 2.5}},
    )
    assert [d.as_document() for d in compare(recorded, replayed).differences] == [
        {"cell": "cell-c", "key": "grad_norm", "recorded": None, "replayed": 2.5},
        {"cell": "cell-c", "key": "loss", "recorded": None, "replayed": 0.75},
    ]


@pytest.mark.parametrize("side", ["recorded", "replayed"])
def test_an_empty_cell_on_one_side_only_is_still_a_difference(tmp_path: Path, side: str) -> None:
    """9.2: 8.2 permits an empty `values`, and such a cell must not vanish quietly.

    Both directions, because the rule lives in two places in any
    implementation that walks each side's cells in turn, and a one-sided test
    would leave the other unwitnessed.
    """
    shared: dict[str, dict[str, float | str]] = {"cell-a": {"loss": 0.5}}
    with_empty = {**shared, "cell-empty": {}}
    recorded = a_record(tmp_path / "recorded", with_empty if side == "recorded" else shared)
    replayed = a_record(tmp_path / "replayed", shared if side == "recorded" else with_empty)
    assert [d.as_document() for d in compare(recorded, replayed).differences] == [
        {"cell": "cell-empty", "key": None, "recorded": None, "replayed": None}
    ]


def test_an_empty_cell_both_sides_hold_is_not_a_difference(tmp_path: Path) -> None:
    """The companion of the test above, and the one that stops it over-reaching.

    8.2 permits an empty `values`, so a cell both sides hold with no values is
    a position where nothing moved. An implementation that asked whether the
    other side's values were *falsy* rather than whether the cell was there at
    all would report a difference here, and would still pass every test above.
    """
    rows: dict[str, dict[str, float | str]] = {"cell-a": {"loss": 0.5}, "cell-empty": {}}
    recorded = a_record(tmp_path / "recorded", rows)
    replayed = a_record(tmp_path / "replayed", rows)
    assert [row.cell for row in recorded.rows] == ["cell-a", "cell-empty"]
    assert compare(recorded, replayed).matched


def test_replay_only_positions_come_after_every_recorded_position(tmp_path: Path) -> None:
    """9.2's order: all of the record's positions, then the re-execution's own.

    The two differences are in different cells, so an implementation that
    grouped by cell -- reporting `cell-a`'s extra value beside `cell-a`'s
    recorded ones -- would produce the same pair in the other order.
    """
    recorded = a_record(
        tmp_path / "recorded", {"cell-a": {"loss": 0.5}, "cell-b": {"loss": 0.25}}
    )
    replayed = a_record(
        tmp_path / "replayed", {"cell-a": {"loss": 0.5, "extra": 1.5}, "cell-b": {"loss": 0.75}}
    )
    assert [d.as_document() for d in compare(recorded, replayed).differences] == [
        {"cell": "cell-b", "key": "loss", "recorded": 0.25, "replayed": 0.75},
        {"cell": "cell-a", "key": "extra", "recorded": None, "replayed": 1.5},
    ]


def test_the_report_writes_a_non_finite_value_as_section_8_2s_wrapper(tmp_path: Path) -> None:
    """A report is read, so it carries a value every JSON parser accepts (8.2)."""
    recorded = a_record(tmp_path / "recorded", {"cell-a": {"loss": math.nan}})
    replayed = a_record(tmp_path / "replayed", {"cell-a": {"loss": -math.inf}})
    report = compare(recorded, replayed)
    assert report.as_document() == {
        "matched": False,
        "record_unfinished": False,
        "differences": [
            {
                "cell": "cell-a",
                "key": "loss",
                "recorded": {"nonfinite": "NaN"},
                "replayed": {"nonfinite": "-Infinity"},
            }
        ],
    }


# --- 9.3: how two values compare ----------------------------------------------


def test_nan_matches_nan(tmp_path: Path, fixture_experiment: str, clean_inputs: None) -> None:
    """Review Focus 3: `NaN != NaN`, so a naive diff reports a run against itself."""
    INPUTS["loss"] = math.nan
    recorded = a_recorded_run(tmp_path, fixture_experiment)
    assert math.isnan(read_record(recorded).rows[0].values["loss"])  # type: ignore[arg-type]
    report = replay(
        recorded,
        experiment=fixture_experiment,
        into=tmp_path / "replayed",
        provenance=a_provenance("run-0002"),
    )
    assert report.matched, "a run must not diverge from itself because of a NaN"


def test_the_nan_check_fails_against_an_implementation_that_uses_equality() -> None:
    """The check above biting: `==` gives the opposite answer on the same input."""
    assert values_match(math.nan, math.nan) is True
    assert naive_match(math.nan, math.nan) is False


def test_nan_differs_from_a_number_and_from_a_string() -> None:
    assert values_match(math.nan, 0.0) is False
    assert values_match(0.0, math.nan) is False
    assert values_match(math.nan, "NaN") is False


def test_infinity_is_compared_by_the_value_the_wrapper_names() -> None:
    assert values_match(math.inf, math.inf) is True
    assert values_match(-math.inf, -math.inf) is True
    assert values_match(math.inf, -math.inf) is False
    assert values_match(math.inf, 1e308) is False
    assert values_match(1e308, math.inf) is False


def test_a_string_is_compared_exactly() -> None:
    assert values_match("converged", "converged") is True
    assert values_match("converged", "Converged") is False
    assert values_match("converged", " converged") is False
    assert values_match("0.5", 0.5) is False
    assert values_match(0.5, "0.5") is False


@pytest.mark.parametrize(
    ("recorded", "replayed", "equal", "why"),
    [
        (1.0, 1.0, True, "identical"),
        # |a - b| is 5.000000413701855e-10 and the bound is 1.0000000005e-9.
        (1.0, 1.0000000005, True, "inside the relative bound"),
        # |a - b| is about 1e-6 and the bound is about 1e-9.
        (1.0, 1.000001, False, "outside the relative bound"),
        # The relative bound is 1e-9 * 1e-13 = 1e-22, so the absolute floor decides.
        (0.0, 1e-13, True, "inside the absolute floor"),
        (0.0, 1e-11, False, "outside the absolute floor"),
        (0.0, ABSOLUTE_TOLERANCE, True, "exactly on the absolute floor, which is inclusive"),
        (0.0, -0.0, True, "signed zero: the difference is zero"),
        # The relative part scales, so the same absolute gap passes at 1e6 and
        # fails at 1.0. |1e6 - (1e6 + 1e-4)| is 9.999994654208422e-05 against a
        # bound of 1.0000000000001e-3; at unit magnitude the bound is 1.0001e-9.
        (1e6, 1e6 + 1e-4, True, "inside the relative bound at a large magnitude"),
        (1.0, 1.0 + 1e-4, False, "outside the relative bound at unit magnitude"),
    ],
)
def test_the_float_tolerance_is_relative_and_absolute(
    recorded: float, replayed: float, equal: bool, why: str
) -> None:
    assert values_match(recorded, replayed) is equal, why
    assert values_match(replayed, recorded) is equal, f"{why}, and 9.3's formula is symmetric"


def test_the_tolerance_constants_are_the_ones_section_9_3_states() -> None:
    assert (RELATIVE_TOLERANCE, ABSOLUTE_TOLERANCE) == (1e-9, 1e-12)


@pytest.mark.parametrize(
    ("relative", "absolute", "recorded", "replayed", "still_equal"),
    [
        (0.0, ABSOLUTE_TOLERANCE, 1.0, 1.0000000005, False),
        (RELATIVE_TOLERANCE, 0.0, 0.0, 1e-13, False),
    ],
)
def test_each_half_of_the_tolerance_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch,
    relative: float,
    absolute: float,
    recorded: float,
    replayed: float,
    still_equal: bool,
) -> None:
    """Both halves bite: with either zeroed, a pair 9.3 calls equal differs.

    This is what stops `test_the_float_tolerance_is_relative_and_absolute` from
    passing against an implementation that is exact, or relative only, or
    absolute only -- each of which would satisfy some of its rows.
    """
    assert values_match(recorded, replayed) is True
    monkeypatch.setattr(replay_module, "RELATIVE_TOLERANCE", relative)
    monkeypatch.setattr(replay_module, "ABSOLUTE_TOLERANCE", absolute)
    assert values_match(recorded, replayed) is still_equal


# --- 9.4: a caller that needs a refusal derives it from the report -------------


def test_raise_if_diverged_carries_the_registry_code_and_the_report() -> None:
    """Each of 9.2's three position shapes reaches the refusal by its own name."""
    report = DiffReport(
        matched=False,
        record_unfinished=False,
        differences=(
            Difference(cell=None, key="deps_hash", recorded=DEPS_HASH, replayed=None),
            Difference(cell="cell-a", key="loss", recorded=0.5, replayed=0.25),
            Difference(cell="cell-empty", key=None, recorded=None, replayed=None),
        ),
    )
    with pytest.raises(ReplayError) as exc:
        report.raise_if_diverged()
    assert exc.value.code == LAB_409
    assert exc.value.report == report
    assert "deps_hash" in str(exc.value)
    assert "cell-a.loss" in str(exc.value)
    assert "cell-empty" in str(exc.value), (
        "a cell with no value to name is still named, because the naming is the "
        "finding (9.1) and 9.2 keeps that difference in the report"
    )


def test_raise_if_diverged_is_silent_on_a_match() -> None:
    DiffReport(matched=True, record_unfinished=False, differences=()).raise_if_diverged()


def test_replay_error_is_a_runtime_error_and_not_a_heph_error() -> None:
    """The convention `lab.config` settled: a lab refusal is a plain builtin.

    `hephkit.lab` sits below research code rather than behind an HTTP boundary,
    so its refusals carry no `status`, `title` or `type_url`; `.code` is there
    for correlation and for the registry's disambiguation.
    """
    report = DiffReport(matched=True, record_unfinished=False, differences=())
    error = ReplayError("diverged", report)
    assert isinstance(error, RuntimeError)
    assert not isinstance(error, HephError)
    assert error.code == LAB_409
    assert error.report is report


def test_the_module_exports_what_the_tests_reach_for() -> None:
    """Every name this file imports is public, so the suite tests the API."""
    assert set(replay_module.__all__) == {
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
    }, "every public name is reached by this suite, and nothing else is exported"


def test_the_module_carries_its_maturity_label() -> None:
    """`tools/check_modules.py` reads this; a missing label fails the repo check."""
    doc: str | None = replay_module.__doc__
    assert doc is not None and doc.rstrip().endswith("Maturity: experimental.")


def test_compare_writes_nothing_and_repeats_itself(tmp_path: Path) -> None:
    """A report may be recomputed from the same two records and read the same way."""
    recorded = a_record(tmp_path / "recorded", {"cell-a": {"loss": 0.5}})
    replayed = a_record(tmp_path / "replayed", {"cell-a": {"loss": 0.25}})
    before = sorted(p.name for p in tmp_path.iterdir())
    first = compare(recorded, replayed)
    second = compare(recorded, replayed)
    assert first == second
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_every_row_comparison_goes_through_values_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One comparison for the rows, so 9.3 is implemented once and tested in one place.

    With it replaced by a function that calls everything different, two
    identical records report every position they hold -- which they could not
    do if any part of the row comparison had its own equality test.
    """
    rows: dict[str, dict[str, float | str]] = {"cell-a": {"loss": 0.5, "note": "converged"}}
    recorded = a_record(tmp_path / "recorded", rows)
    replayed = a_record(tmp_path / "replayed", rows)
    assert compare(recorded, replayed).matched

    def everything_moved(recorded_value: float | str, replayed_value: float | str) -> bool:
        return False

    monkeypatch.setattr(replay_module, "values_match", everything_moved)
    assert [d.as_document() for d in compare(recorded, replayed).differences] == [
        {"cell": "cell-a", "key": "loss", "recorded": 0.5, "replayed": 0.5},
        {"cell": "cell-a", "key": "note", "recorded": "converged", "replayed": "converged"},
    ]
