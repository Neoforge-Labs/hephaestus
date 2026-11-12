"""Integrity gates, each one shown firing on a violating fixture (no spec section).

`lab.gates` has no normative section: sections 8 and 9 define records and
replay, and a gate is a policy over them rather than a new wire contract. Design
9.3 therefore assigns it **contract tests with violating fixtures**, and that is
what this file is, because a gate that has never been shown to fire is
indistinguishable from a passing codebase.

Three habits make these checks bite rather than merely pass.

**Every gate has a violating fixture and a clean one.** The figures gate reads
`tests/fixtures/violations/figure_with_literals.py`, which marks each line it
expects to be flagged with a trailing marker comment, so the fixture states its
own expectations and this file hard-codes no line numbers. Two tests guard the
fixtures themselves: one asserts the violating fixture declares violations to
find, the other that the clean one declares none. Without those, a missing
fixture would make the pair of tests vacuously green.

**An absence is paired with the implementation that would break it.**
:func:`text_scan` is the regex over source the design forbids, and the docstring
test asserts that it gives the opposite answer on the same input -- so "a metric
named in a docstring is not flagged" is a check with a demonstrated bite rather
than an assertion about an implementation nobody wrote. :func:`no_violations` is
the gate that cannot fire, used to show that `check_all` refuses on what a gate
found rather than on being called.

**A hook records what it received.** The replay check that
:func:`~hephkit.lab.gates.check_cited_runs` accepts is a
:class:`RecordingReplay` in these tests, so "the replay check is not called for
a citation that already failed" is an assertion about the calls that happened
rather than about ambient state.
"""

from __future__ import annotations

import ast
import json
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

import pytest
from hephkit.errors import LAB_412, LAB_424, HephError
from hephkit.hashing import canonical_json
from hephkit.lab.gates import (
    CITATION,
    CITATIONS,
    FIGURES,
    METRIC_WORDS,
    RECORDS,
    TUNING_WORDS,
    GateError,
    MissingSubjectError,
    Violation,
    check_all,
    check_cited_runs,
    check_records_wellformed,
    cited_runs,
    find_hardcoded_metrics,
    names_a_metric,
    raise_if_violated,
    record_directories,
)
from hephkit.lab.record import (
    PROVENANCE_NAME,
    ROWS_NAME,
    SUMMARY_NAME,
    RecordError,
    RunRecord,
    open_record,
    read_record,
)
from hephkit.lab.replay import Difference, DiffReport
from hephkit.lab.repro import ProvenanceRecord
from pydantic import ValidationError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "violations"
VIOLATING_FIGURE = FIXTURES / "figure_with_literals.py"
CLEAN_FIGURE = FIXTURES / "figure_clean.py"

#: The marker the violating fixture puts on each line the gate must flag.
MARKER = "# VIOLATION"

# Content hashes (spec 4.2) quoted from `conformance/hashing/content.json`
# (`empty-object`, `null`, `key-order-does-not-change-hash`), so no hash string
# here is of unknown origin.
CONFIG_HASH = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
DATA_HASH = "sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"
DEPS_HASH = "sha256:d3626ac30a87e6f7a6428233b3c68299976865fa5508e4267c5415c76af7a772"

#: A synthetic commit SHA, 40 lowercase hex, as `conformance/lab/record.json` uses.
CODE_SHA = "c0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ff"

ENVIRONMENT = {
    "platform": "macOS-15.6-arm64",
    "python": "3.12.7",
    "frameworks": {"numpy": "2.1.3", "torch": None},
    "accelerator": None,
}


def a_provenance(run_id: str = "run-0001") -> ProvenanceRecord:
    """A section 7 record, built by hand rather than captured.

    Hand-built so every assertion here is about the gates rather than about the
    machine the suite runs on; `class` is a member name and not a Python
    identifier, so the model is validated from a document.
    """
    return ProvenanceRecord.model_validate(
        {
            "run_id": run_id,
            "config_hash": CONFIG_HASH,
            "data_hash": DATA_HASH,
            "deps_hash": DEPS_HASH,
            "code_sha": CODE_SHA,
            "class": "deterministic",
            "environment": dict(ENVIRONMENT),
        }
    )


def a_record(
    directory: Path,
    rows: Mapping[str, Mapping[str, float | str]] | None = None,
    run_id: str | None = None,
) -> Path:
    """Write a finished record at `directory`, named for the run it records."""
    rows = {"cell-a": {"loss": 0.5}} if rows is None else rows
    name = directory.name if run_id is None else run_id
    with open_record(directory, a_provenance(name)) as record:
        for cell, values in rows.items():
            record.append_row(cell, values)
    return directory


def an_unfinished_record(directory: Path) -> Path:
    """A record whose run did not reach its end (spec 8.4): rows, and no summary.

    Built the way 8.4 says one comes about -- the run ends by failing, so the
    context manager writes no summary -- rather than by deleting a file
    afterwards, which would be a record somebody edited rather than a run that
    died.
    """
    with pytest.raises(RuntimeError, match="the run died"):
        with open_record(directory, a_provenance(directory.name)) as record:
            record.append_row("cell-a", {"loss": 0.5})
            raise RuntimeError("the run died")
    assert not read_record(directory).complete, "8.4: no summary means unfinished"
    return directory


def a_record_whose_summary_disagrees(directory: Path) -> Path:
    """The audit's second finding: a record whose summary disagrees with its rows.

    The rows are written by `lab.record`, so this is a real record; only the
    summary is rewritten, which is the hand-edit that makes a record stop being
    evidence.
    """
    a_record(directory, {"cell-a": {"loss": 0.5}, "cell-b": {"loss": 1.0}})
    lying = {"run_id": directory.name, "cells": ["cell-a"], "rows": 1}
    (directory / SUMMARY_NAME).write_text(canonical_json(lying), encoding="utf-8")
    return directory


def a_record_with_a_duplicate_cell(directory: Path) -> Path:
    """A record naming one cell twice, which spec 8.2 forbids."""
    a_record(directory, {"cell-a": {"loss": 0.5}})
    rows = directory / ROWS_NAME
    rows.write_text(rows.read_text(encoding="utf-8") * 2, encoding="utf-8")
    return directory


def a_record_with_no_rows_file(directory: Path) -> Path:
    """A directory that claims to be a record and is missing one of its documents."""
    directory.mkdir(parents=True)
    document = a_provenance(directory.name).as_document()
    (directory / PROVENANCE_NAME).write_text(canonical_json(document), encoding="utf-8")
    return directory


def a_manuscript(path: Path, *runs: str) -> Path:
    """A manuscript citing each of `runs` in this module's citation form."""
    cites = " and ".join(f"run:{run}" for run in runs)
    path.write_text(
        f"## Results\n\nTable 2 reports the macro F1 of {cites}.\n",
        encoding="utf-8",
    )
    return path


def marked_lines(path: Path) -> set[str]:
    """The `path:line` subject of every line the fixture marks as a violation."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return {f"{path}:{number}" for number, line in enumerate(lines, 1) if MARKER in line}


def scan_source(source: str) -> list[Violation]:
    """Scan one source string as a file, through the public gate."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "figure.py"
        path.write_text(source, encoding="utf-8")
        return find_hardcoded_metrics([path])


def text_scan(source: str) -> list[str]:
    """The scan the design forbids: a regex over the source text.

    Used by the docstring test to show that the same input gets the opposite
    answer from it, so "a metric named in a docstring or a comment is not
    flagged" has a witness rather than an assertion about an implementation
    nobody wrote. It is also why the gate parses: this finds the hyperparameters
    and the figure geometry in the clean fixture too.
    """
    return re.findall(r"\b([a-z_0-9]+)\s*=\s*-?\d+\.\d+", source)


def no_violations(*args: object, **kwargs: object) -> list[Violation]:
    """The gate that cannot fire, for showing what `check_all` refuses on."""
    return []


class RecordingReplay:
    """A replay check that records what it was asked about, and what it answered.

    `check_cited_runs` takes the replay as a parameter precisely because a gate
    cannot capture the re-execution's provenance itself (see the module
    docstring of `lab.gates`). Recording the calls is how these tests assert
    which citations reached it.
    """

    def __init__(self, report: DiffReport) -> None:
        self.report = report
        self.calls: list[tuple[str, Path]] = []

    def __call__(self, run_id: str, record: Path) -> DiffReport:
        self.calls.append((run_id, record))
        return self.report


MATCHED = DiffReport(matched=True, record_unfinished=False, differences=())
DIVERGED = DiffReport(
    matched=False,
    record_unfinished=False,
    differences=(Difference(cell="cell-a", key="loss", recorded=0.5, replayed=0.25),),
)


# --- the figures gate: a literal metric in a figure script --------------------


def test_the_violating_figure_fixture_declares_violations_to_find() -> None:
    """Without this, the test below would pass on a fixture that went missing."""
    assert VIOLATING_FIGURE.is_file(), VIOLATING_FIGURE
    assert len(marked_lines(VIOLATING_FIGURE)) >= 10, marked_lines(VIOLATING_FIGURE)


def test_figure_script_with_a_literal_metric_is_caught() -> None:
    """Every line the fixture marks is flagged, and no line it does not."""
    violations = find_hardcoded_metrics([VIOLATING_FIGURE])
    assert {v.subject for v in violations} == marked_lines(VIOLATING_FIGURE)
    assert {v.gate for v in violations} == {FIGURES}


def test_one_literal_under_two_names_is_reported_once() -> None:
    """`best_f1 = best_f1_macro = 0.5210`: the finding is the literal, not the name."""
    violations = find_hardcoded_metrics([VIOLATING_FIGURE])
    doubled = [v for v in violations if "0.521" in v.detail and "best" in v.detail]
    assert len(doubled) == 1, doubled


def test_the_clean_figure_fixture_declares_no_violations() -> None:
    """Without this, "the clean fixture passes" could be true of a missing file."""
    assert CLEAN_FIGURE.is_file(), CLEAN_FIGURE
    assert marked_lines(CLEAN_FIGURE) == set()


def test_a_clean_figure_script_produces_no_violations() -> None:
    assert find_hardcoded_metrics([CLEAN_FIGURE]) == []


def test_the_clean_fixture_is_what_a_text_scan_would_flag() -> None:
    """The clean fixture is not clean by being empty: a regex finds plenty in it."""
    found = set(text_scan(CLEAN_FIGURE.read_text(encoding="utf-8")))
    assert {"learning_rate", "loss_weight", "f1_cutoff", "figure_width"} <= found, found


def test_a_metric_named_in_a_docstring_or_a_comment_is_not_flagged() -> None:
    """The AST never sees a comment, and a docstring is not an assignment.

    Paired with the implementation that would break it: `text_scan` flags both.
    """
    source = (
        '"""Reports f1 = 0.474 for the baseline."""\n'
        "# and recall = 0.655 for the ablation\n"
        "f1 = read_it()\n"
    )
    assert scan_source(source) == []
    assert text_scan(source) == ["f1", "recall"]


def test_an_integer_or_a_string_metric_is_not_flagged() -> None:
    """An integer in research code is a count; a string is a label."""
    assert scan_source("accuracy = 1\nf1_label = 'macro'\nn_correct = 847\n") == []


def test_a_tuning_name_is_not_flagged_although_it_carries_a_metric_word() -> None:
    """`loss_weight` is an input. The veto is what keeps the gate switched on."""
    assert scan_source("loss_weight = 0.25\n") == []
    assert names_a_metric("loss"), "the vocabulary must still hold the metric word"
    assert not names_a_metric("loss_weight")


def test_the_vocabulary_matches_on_words_rather_than_substrings() -> None:
    """Each case is a name the gate must or must not recognise, and why."""
    for name in (
        "f1",  # the audit's own
        "f1_macro",  # a qualified metric
        "finalF1",  # camel case
        "ROC_AUC",  # shouted
        "p_value",  # matches only once the separators are dropped
        "f1_scores",  # a plural whose other word matches outright
        "scores",  # a plural that matches only once the `s` is dropped
        "precisions",  # the same, for a word that is not also a container name
        "losses",  # an irregular plural, listed explicitly
        "error_rate",  # a rate that is a result rather than a knob
        "max_f1",  # the best of several, which is still a reported number
    ):
        assert names_a_metric(name), name
    for name in (
        "learning_rate",  # a hyperparameter
        "SCHEMA_VERSION",  # a version
        "ylim",  # an axis limit
        "figure_width",  # geometry
        "accuracy_threshold",  # a knob named after what it tunes
        "loss_weights",  # the veto, reached through the same plural rule
        "target_f1",  # a goal
        "dropout",  # an input
    ):
        assert not names_a_metric(name), name


def test_the_two_vocabularies_do_not_overlap() -> None:
    """A word in both would make the veto silently delete a metric."""
    assert METRIC_WORDS & TUNING_WORDS == frozenset()


def test_every_assignment_shape_the_gate_claims_is_scanned() -> None:
    """One source per AST node the scan handles, so none is covered by another."""
    shapes = {
        "name": "f1 = 0.474\n",
        "annotated": "f1: float = 0.474\n",
        "attribute": "panel.f1 = 0.474\n",
        "subscript": "table['f1'] = 0.474\n",
        "tuple": "f1, other = 0.474, 'x'\n",
        "list element": "f1 = [0.474]\n",
        "nested dict": "f1 = {'liver': 0.474}\n",
        "dict key": "bars = {'f1': 0.474}\n",
        "negative": "f1 = -0.474\n",
    }
    for shape, source in shapes.items():
        assert len(scan_source(source)) == 1, f"{shape}: {source!r}"


def test_a_target_with_no_name_to_match_is_skipped() -> None:
    """A computed subscript and a starred target bind no name the gate can read."""
    assert scan_source("table[0] = 0.474\n") == []
    assert scan_source("other, *rest = [0.474]\n") == []


def test_an_unpacking_the_gate_cannot_pair_falls_back_to_the_whole_value() -> None:
    """`f1, *rest = [0.474]` does assign 0.474 to f1, so the literal is still found."""
    assert len(scan_source("f1, *rest = [0.474]\n")) == 1


def test_a_directory_is_walked_for_python_files(tmp_path: Path) -> None:
    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "_gen_figures.py").write_text("f1 = 0.474\n", encoding="utf-8")
    (tmp_path / "figures" / "notes.txt").write_text("f1 = 0.474\n", encoding="utf-8")
    violations = find_hardcoded_metrics([tmp_path])
    assert [v.subject for v in violations] == [f"{tmp_path / 'figures' / '_gen_figures.py'}:1"]


def test_a_file_that_does_not_parse_is_a_violation_rather_than_a_pass(tmp_path: Path) -> None:
    """A file the gate could not read is not a file the gate passed."""
    broken = tmp_path / "broken.py"
    broken.write_text("f1 = 0.474\ndef (\n", encoding="utf-8")
    violations = find_hardcoded_metrics([broken])
    assert len(violations) == 1, violations
    assert "could not be parsed" in violations[0].detail


def test_a_figure_path_that_is_not_there_is_refused_as_a_missing_subject(
    tmp_path: Path,
) -> None:
    """412's registry entry: a gate cannot pass on an artefact that is not there."""
    with pytest.raises(MissingSubjectError) as caught:
        find_hardcoded_metrics([tmp_path / "absent"])
    assert caught.value.code == LAB_424


# --- the records gate: a record whose summary disagrees with its rows ---------


def test_the_records_scan_has_records_to_scan(tmp_path: Path) -> None:
    """An empty scan would make every check below pass by covering nothing."""
    a_record(tmp_path / "run-0001")
    a_record(tmp_path / "nested" / "run-0002")
    assert record_directories(tmp_path) == [
        tmp_path / "nested" / "run-0002",
        tmp_path / "run-0001",
    ]


def test_record_whose_summary_disagrees_with_its_rows_is_caught(tmp_path: Path) -> None:
    """The audit's second finding: such a record "is not evidence"."""
    directory = a_record_whose_summary_disagrees(tmp_path / "run-0001")
    violations = check_records_wellformed(tmp_path)
    assert [v.subject for v in violations] == [str(directory)]
    assert violations[0].gate == RECORDS
    assert "disagrees with its rows" in violations[0].detail


def test_a_record_naming_one_cell_twice_is_caught(tmp_path: Path) -> None:
    directory = a_record_with_a_duplicate_cell(tmp_path / "run-0001")
    violations = check_records_wellformed(tmp_path)
    assert [v.subject for v in violations] == [str(directory)]
    assert "repeats the cell" in violations[0].detail


def test_a_well_formed_record_tree_produces_no_violations(tmp_path: Path) -> None:
    a_record(tmp_path / "run-0001")
    a_record(tmp_path / "run-0002", {"cell-a": {"loss": 0.5}, "cell-b": {"note": "x"}})
    assert check_records_wellformed(tmp_path) == []


def test_an_unfinished_record_is_not_malformed(tmp_path: Path) -> None:
    """8.4 makes an unfinished record a run that died, not a broken artefact.

    The citations gate is where citing one is refused; this gate reads records,
    and a record with no summary is one `read_record` accepts.
    """
    an_unfinished_record(tmp_path / "run-0001")
    assert check_records_wellformed(tmp_path) == []


def test_a_record_missing_one_of_its_documents_raises_424_not_a_violation(
    tmp_path: Path,
) -> None:
    """424's entry owns an absent artefact, and this gate does not relabel it."""
    a_record_with_no_rows_file(tmp_path / "run-0001")
    with pytest.raises(RecordError) as caught:
        check_records_wellformed(tmp_path)
    assert caught.value.code == LAB_424
    assert ROWS_NAME in str(caught.value)


def test_a_records_path_that_is_not_there_is_refused_as_a_missing_subject(
    tmp_path: Path,
) -> None:
    with pytest.raises(MissingSubjectError) as caught:
        check_records_wellformed(tmp_path / "absent")
    assert caught.value.code == LAB_424


# --- the citations gate: a manuscript citing a run ----------------------------


def test_citations_are_read_out_of_the_manuscript(tmp_path: Path) -> None:
    """The convention, and the three things that look like it and are not."""
    manuscript = tmp_path / "paper.md"
    manuscript.write_text(
        "We cite run:run-0001, and run:run-0002. Again run:run-0001.\n"
        "A rerun:run-0003 is not a citation, nor is overrun:run-0004, nor a bare run:.\n",
        encoding="utf-8",
    )
    assert cited_runs(manuscript) == ["run-0001", "run-0002"]


def test_a_citation_does_not_swallow_the_sentence_punctuation(tmp_path: Path) -> None:
    manuscript = tmp_path / "paper.md"
    manuscript.write_text("See run:run-0001.\n", encoding="utf-8")
    assert cited_runs(manuscript) == ["run-0001"]
    assert CITATION.search("run:run-0001.") is not None


def test_manuscript_citing_a_missing_run_is_caught(tmp_path: Path) -> None:
    """The audit's third finding: "a manuscript citing a run that does not exist"."""
    records = tmp_path / "records"
    records.mkdir()
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    violations = check_cited_runs(manuscript, records)
    assert [v.subject for v in violations] == ["run-0001"]
    assert violations[0].gate == CITATIONS
    assert "no record" in violations[0].detail


def test_manuscript_citing_an_unfinished_run_is_caught(tmp_path: Path) -> None:
    """A run record that is not citable: the run never reached its end (8.4)."""
    records = tmp_path / "records"
    an_unfinished_record(records / "run-0001")
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    violations = check_cited_runs(manuscript, records)
    assert [v.subject for v in violations] == ["run-0001"]
    assert "unfinished" in violations[0].detail


def test_manuscript_citing_a_malformed_record_is_caught(tmp_path: Path) -> None:
    records = tmp_path / "records"
    a_record_whose_summary_disagrees(records / "run-0001")
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    violations = check_cited_runs(manuscript, records)
    assert [v.subject for v in violations] == ["run-0001"]
    assert "disagrees with its rows" in violations[0].detail


def test_a_record_filed_under_another_runs_name_is_caught(tmp_path: Path) -> None:
    """The directory names the run it records, so a mismatch is a mis-filed record."""
    records = tmp_path / "records"
    a_record(records / "run-0001", run_id="run-0002")
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    violations = check_cited_runs(manuscript, records)
    assert [v.subject for v in violations] == ["run-0001"]
    assert "run-0002" in violations[0].detail


def test_manuscript_citing_an_unreplayable_run_is_caught(tmp_path: Path) -> None:
    """A diverged replay of a cited run, reported through `raise_if_diverged`."""
    records = tmp_path / "records"
    a_record(records / "run-0001")
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    replay = RecordingReplay(DIVERGED)
    violations = check_cited_runs(manuscript, records, replay_check=replay)
    assert [v.subject for v in violations] == ["run-0001"]
    assert "cell-a.loss" in violations[0].detail
    assert replay.calls == [("run-0001", records / "run-0001")]


def test_a_replayable_citation_produces_no_violations(tmp_path: Path) -> None:
    records = tmp_path / "records"
    a_record(records / "run-0001")
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    replay = RecordingReplay(MATCHED)
    assert check_cited_runs(manuscript, records, replay_check=replay) == []
    assert replay.calls == [("run-0001", records / "run-0001")]


def test_a_citable_run_passes_without_a_replay_check(tmp_path: Path) -> None:
    """Without a replay the gate checks replayability, which is all it can know."""
    records = tmp_path / "records"
    a_record(records / "run-0001")
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    assert check_cited_runs(manuscript, records) == []


def test_the_replay_check_is_not_called_for_a_citation_that_already_failed(
    tmp_path: Path,
) -> None:
    """A record that is absent, unfinished or malformed never reaches a replay."""
    records = tmp_path / "records"
    an_unfinished_record(records / "run-0002")
    a_record_whose_summary_disagrees(records / "run-0003")
    a_record(records / "run-0004")
    manuscript = a_manuscript(
        tmp_path / "paper.md", "run-0001", "run-0002", "run-0003", "run-0004"
    )
    replay = RecordingReplay(MATCHED)
    violations = check_cited_runs(manuscript, records, replay_check=replay)
    assert [v.subject for v in violations] == ["run-0001", "run-0002", "run-0003"]
    assert replay.calls == [("run-0004", records / "run-0004")]


def test_a_manuscript_with_no_citations_has_nothing_to_check(tmp_path: Path) -> None:
    """Stated rather than assumed: this gate judges citations, not whether any exist."""
    records = tmp_path / "records"
    a_record(records / "run-0001")
    manuscript = tmp_path / "paper.md"
    manuscript.write_text("## Results\n\nNo run is cited here.\n", encoding="utf-8")
    assert cited_runs(manuscript) == []
    assert check_cited_runs(manuscript, records) == []


def test_a_manuscript_that_is_not_there_is_refused_as_a_missing_subject(
    tmp_path: Path,
) -> None:
    records = tmp_path / "records"
    records.mkdir()
    with pytest.raises(MissingSubjectError) as caught:
        check_cited_runs(tmp_path / "absent.md", records)
    assert caught.value.code == LAB_424


def test_a_citations_records_root_that_is_not_there_is_refused(tmp_path: Path) -> None:
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    with pytest.raises(MissingSubjectError) as caught:
        check_cited_runs(manuscript, tmp_path / "absent")
    assert caught.value.code == LAB_424


# --- check_all, and the refusal CI sees ---------------------------------------


def test_check_all_raises_with_every_gates_findings(tmp_path: Path) -> None:
    """The one call CI makes, refusing on what the gates found."""
    records = tmp_path / "records"
    a_record_whose_summary_disagrees(records / "run-0002")
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    with pytest.raises(GateError) as caught:
        check_all(figures=[VIOLATING_FIGURE], records=records, manuscript=manuscript)
    error = caught.value
    assert error.code == LAB_412
    assert {v.gate for v in error.violations} == {FIGURES, RECORDS, CITATIONS}
    assert {v.subject for v in error.violations} == marked_lines(VIOLATING_FIGURE) | {
        str(records / "run-0002"),
        "run-0001",
    }


def test_check_all_runs_only_the_gates_it_was_given(tmp_path: Path) -> None:
    """Each argument switches one gate on, so a project adopts them one at a time."""
    with pytest.raises(GateError) as caught:
        check_all(figures=[VIOLATING_FIGURE])
    assert {v.gate for v in caught.value.violations} == {FIGURES}
    records = tmp_path / "records"
    a_record_whose_summary_disagrees(records / "run-0001")
    with pytest.raises(GateError) as caught:
        check_all(records=records)
    assert {v.gate for v in caught.value.violations} == {RECORDS}


def test_check_all_passes_on_clean_inputs(tmp_path: Path) -> None:
    records = tmp_path / "records"
    a_record(records / "run-0001")
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    assert check_all(figures=[CLEAN_FIGURE], records=records, manuscript=manuscript) == []


def test_check_all_refuses_to_check_nothing() -> None:
    """A gate run over no subject at all passes by checking nothing."""
    with pytest.raises(ValueError, match="nothing to check"):
        check_all()


def test_check_all_refuses_a_manuscript_with_no_records_to_resolve_it(
    tmp_path: Path,
) -> None:
    manuscript = a_manuscript(tmp_path / "paper.md", "run-0001")
    with pytest.raises(ValueError, match="records"):
        check_all(manuscript=manuscript)


def test_raise_if_violated_is_silent_on_an_empty_list() -> None:
    assert raise_if_violated([]) is None


def test_raise_if_violated_names_what_was_found() -> None:
    found = [Violation(gate=FIGURES, subject="f.py:1", detail="f1 is 0.474")]
    with pytest.raises(GateError) as caught:
        raise_if_violated(found)
    assert caught.value.violations == tuple(found)
    assert "f.py:1" in str(caught.value)


def test_check_all_refuses_on_what_a_gate_found_rather_than_on_being_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paired with the gate that cannot fire: with it, the same call passes."""
    records = tmp_path / "records"
    a_record_whose_summary_disagrees(records / "run-0001")
    with pytest.raises(GateError):
        check_all(records=records)
    monkeypatch.setattr("hephkit.lab.gates.check_records_wellformed", no_violations)
    assert check_all(records=records) == []


def test_a_gate_refusal_is_not_a_heph_error() -> None:
    """Every refusal in `hephkit.lab` is a ValueError/RuntimeError, never HephError."""
    assert issubclass(GateError, RuntimeError)
    assert not issubclass(GateError, HephError)
    assert issubclass(MissingSubjectError, GateError)


def test_a_violation_is_frozen_and_closed() -> None:
    violation = Violation(gate=FIGURES, subject="f.py:1", detail="f1 is 0.474")
    assert violation.as_document() == {
        "gate": FIGURES,
        "subject": "f.py:1",
        "detail": "f1 is 0.474",
    }
    assert json.loads(canonical_json(violation.as_document()))["gate"] == FIGURES
    with pytest.raises(ValidationError):
        Violation(gate=FIGURES, subject="f.py:1", detail="x", extra=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        violation.gate = RECORDS  # type: ignore[misc]


def test_the_violating_fixture_is_parsed_rather_than_imported() -> None:
    """`ast.parse` is the only thing that reads it, so nothing in it ever runs."""
    assert isinstance(ast.parse(VIOLATING_FIGURE.read_text(encoding="utf-8")), ast.Module)


def test_the_record_helpers_build_records_the_record_module_accepts(tmp_path: Path) -> None:
    """The gates above are therefore tested against real records, not stand-ins."""
    directory = a_record(tmp_path / "run-0001")
    record = read_record(directory)
    assert isinstance(record, RunRecord)
    assert record.complete
    assert record.provenance.run_id == "run-0001"
