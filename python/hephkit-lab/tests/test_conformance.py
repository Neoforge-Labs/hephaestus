"""Run the `lab.*` conformance vectors through the Python API.

Vector files are discovered by globbing `conformance/lab/*.json`. A file whose
`suite` has no runner here is a hard failure, never a skip: a new vector file
must not be silently untested. This mirrors
`python/hephkit/tests/test_conformance.py`, which owns every other area and
exempts `lab/` because it must keep zero runtime dependencies.

The `lab.record` runner borrows `test_repro.py`'s git fixture helpers rather
than growing a second copy of them: the vectors and the unit tests must agree
on what "a clean tree" is, and two builders would eventually disagree.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import env_rules
import pytest
import test_repro
from pydantic import ValidationError, create_model

from hephkit.lab.config import ConfigError, ExperimentConfig, config_hash, resolve
from hephkit.lab.record import NONFINITE, NONFINITE_MEMBER, RunRecord, open_record, read_record
from hephkit.lab.replay import compare
from hephkit.lab.repro import Accelerator, ProvenanceRecord, capture

ROOT = Path(__file__).resolve().parents[3] / "conformance"
LAB = ROOT / "lab"

Case = dict[str, Any]

#: What a `lab.record` case writes for "the commit HEAD resolves to", which no
#: vector file can hold, since the fixture repository is built per run.
HEAD_SENTINEL = "<head>"

#: The scalar type names a `lab.config` vector's `model` may use.
SCALARS: dict[str, type] = {"int": int, "float": float, "str": str, "bool": bool}


def build_model(name: str, shape: Mapping[str, Any]) -> type[ExperimentConfig]:
    """Turn a vector's `model` description into a pydantic model.

    A member whose value is a string names a scalar type; a member whose value
    is an object is a nested config. Every member is required, so a case that
    leaves one unset pins the refusal rather than a default.
    """
    fields: dict[str, Any] = {}
    for key, value in shape.items():
        if isinstance(value, dict):
            fields[key] = (build_model(f"{name}_{key}", value), ...)
        else:
            fields[key] = (SCALARS[value], ...)
    return create_model(name, __base__=ExperimentConfig, **fields)  # type: ignore[call-overload,no-any-return]


def run_config(case: Case, tmp_path: Path) -> None:
    i = case["input"]
    model = build_model("VectorConfig", i["model"])
    path: Path | None = None
    if "file" in i:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(i["file"]), encoding="utf-8")
    elif i.get("missing_file"):
        # A path that does not exist: the file layer is absent rather than wrong.
        path = tmp_path / "absent.json"

    def compute() -> ExperimentConfig:
        return resolve(
            model,
            defaults=i.get("defaults", {}),
            file=path,
            env=i.get("env", {}),
            argv=i.get("argv", []),
        )

    expect = case["expect"]
    if "error" in expect:
        with pytest.raises(ConfigError) as exc:
            compute()
        assert exc.value.code == expect["error"]
        if "field" in expect:
            assert exc.value.field == expect["field"]
        return
    cfg = compute()
    if "config" in expect:
        assert cfg.model_dump(mode="json") == expect["config"]
    if "hash" in expect:
        assert config_hash(cfg) == expect["hash"]


def build_repo(spec: Mapping[str, Any], tmp_path: Path) -> Path:
    """Build the repository fixture a `lab.record` case describes.

    git is what puts the fixture into each state and what confirms it reached
    it, so the `<head>` the case expects comes from `git rev-parse HEAD` rather
    than from the code under test.
    """
    tree = test_repro.a_tree(tmp_path, lockfile=spec["lockfile"])
    state = spec["git"]
    if state == "absent":
        return tree
    test_repro.git(tree, "init", "-b", "main")
    if state == "no-commits":
        assert test_repro.head(tree) is None, "the fixture is meant to hold no commit"
        return tree
    test_repro.git(tree, "add", "-A")
    test_repro.git(tree, "commit", "-m", "first")
    commit = test_repro.head(tree)
    assert commit is not None, "the fixture is meant to hold a commit"
    if state == "detached":
        test_repro.git(tree, "checkout", "--detach", commit)
        assert "HEAD detached" in test_repro.git(tree, "status")
    tree_state = spec.get("tree", "clean")
    if tree_state == "modified":
        (tree / "train.py").write_text("print('changed')\n", encoding="utf-8")
    elif tree_state == "untracked":
        (tree / "scratch.py").write_text("x = 1\n", encoding="utf-8")
    elif tree_state == "ignored-untracked":
        (tree / "ignored" / "checkpoint.bin").write_bytes(b"\x00")
    dirty = test_repro.git(tree, "status", "--porcelain") != ""
    assert dirty == (tree_state in {"modified", "untracked"}), (
        f"the {tree_state!r} fixture did not reach the tree state it claims"
    )
    return tree


def run_capture(case: Case, tmp_path: Path) -> None:
    i = case["input"]["capture"]
    repo = build_repo(i["repo"], tmp_path)
    kwargs: dict[str, Any] = {}
    if "frameworks" in i:
        kwargs["frameworks"] = tuple(i["frameworks"])
    if "accelerator" in i:
        answer = i["accelerator"]
        probe = None if answer is None else Accelerator.model_validate(answer)
        kwargs["accelerator_probe"] = lambda: probe
    document = capture(
        run_id=i["run_id"],
        config_hash=i["config_hash"],
        data_hash=i["data_hash"],
        repo=repo,
        **kwargs,
    ).as_document()

    expect = case["expect"]["captured"]
    for member in ("run_id", "config_hash", "data_hash", "deps_hash", "class"):
        if member in expect:
            assert document[member] == expect[member], member
    if expect["code_sha"] == HEAD_SENTINEL:
        head = test_repro.head(repo)
        assert head is not None
        assert document["code_sha"] == head
    else:
        assert document["code_sha"] is None
    environment = document["environment"]
    if "frameworks" in expect:
        assert environment["frameworks"] == expect["frameworks"]
    if "accelerator" in expect:
        assert environment["accelerator"] == expect["accelerator"]
    if "environment_members" in expect:
        assert list(environment) == expect["environment_members"]
    for fact in expect.get("environment_excludes", ()):
        assert env_rules.CHECKS[fact](environment) == [], fact


def _is_array(value: Any) -> bool:
    """A JSON array, which a string is not, however sequence-like it is."""
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def assert_member_order(actual: Any, expected: Any, where: str = "<root>") -> None:
    """Assert `actual` carries `expected`'s members in `expected`'s order, at every depth.

    Equality is not enough and the difference bites: a case that differs from
    its input in nothing but the order of a nested object's members -- which is
    exactly what the non-Python-runtime case pins, since a member 7.4 does not
    name serialises after the ones it does -- passes a top-level order check
    whatever order the nested object came out in.

    Total on purpose, because Tasks 9 to 11 drive their suites through this:

    * It descends into **arrays of objects**, with the index in the path, so a
      later suite whose expectation holds a list of records cannot acquire a
      case that silently cannot fail. No shape in `record.json` needs it today.
    * A value of the wrong **kind** -- a scalar where an object was expected --
      **fails** rather than being skipped. `run_record` happens to be safe
      because its dict-equality assertion runs first, but shared machinery must
      not depend on the order its callers assert things in.

    Scalars are left to the caller's equality assertion: this function is about
    order and shape, and two callers asserting the same equality twice would
    report the second failure in the less readable way.
    """
    if isinstance(expected, Mapping):
        assert isinstance(actual, Mapping), (
            f"expected an object at {where}, got {type(actual).__name__}"
        )
        assert list(actual) == list(expected), f"member order at {where}"
        # `actual[key]` rather than `.get`: the assertion above has already
        # established that both carry the same member names.
        for key, value in expected.items():
            assert_member_order(actual[key], value, f"{where}.{key}")
        return
    if _is_array(expected):
        assert _is_array(actual), f"expected an array at {where}, got {type(actual).__name__}"
        assert len(actual) == len(expected), f"array length at {where}"
        for index, value in enumerate(expected):
            assert_member_order(actual[index], value, f"{where}[{index}]")


def run_record(case: Case, _tmp_path: Path) -> None:
    document = case["input"]["record"]
    expect = case["expect"]
    if "invalid" in expect:
        with pytest.raises(ValidationError):
            ProvenanceRecord.model_validate(document)
        return
    record = ProvenanceRecord.model_validate(document)
    serialised = record.as_document()
    assert serialised == expect["serialised"]
    assert_member_order(serialised, expect["serialised"])


def run_record_case(case: Case, tmp_path: Path) -> None:
    """One `lab.record` case: a capture, or a record document."""
    if "capture" in case["input"]:
        run_capture(case, tmp_path)
    else:
        run_record(case, tmp_path)


def a_row_value(value: Any) -> float | str:
    """A vector's row value as spec 8.2 reads it, undoing the non-finite wrapper.

    The three spellings come from `lab.record`, so the vectors and the writer
    cannot disagree about which value `{"nonfinite": "NaN"}` names.
    """
    if isinstance(value, dict):
        return NONFINITE[value[NONFINITE_MEMBER]]
    return value  # type: ignore[no-any-return]


def build_side(side: Mapping[str, Any], directory: Path) -> RunRecord:
    """Write the record a `lab.diff` case describes, and read it back.

    Written with `open_record` and read with `read_record` rather than
    assembled in memory: a replay compares records that came off a disk, so
    the non-finite wrapper and the canonical-JSON round trip are exercised by
    the code that owns them instead of being reimplemented here.
    """
    provenance = ProvenanceRecord.model_validate(side["provenance"])
    with open_record(directory, provenance) as record:
        for row in side["rows"]:
            record.append_row(
                row["cell"], {name: a_row_value(v) for name, v in row["values"].items()}
            )
    return read_record(directory)


def run_diff(case: Case, tmp_path: Path) -> None:
    """One `lab.diff` case: two records in, one difference report out (spec 9)."""
    recorded = build_side(case["input"]["recorded"], tmp_path / "recorded")
    replayed = build_side(case["input"]["replayed"], tmp_path / "replayed")
    report = compare(recorded, replayed).as_document()
    expect = case["expect"]
    assert report == expect
    assert_member_order(report, expect)


RUNNERS: dict[str, Callable[[Case, Path], None]] = {
    "lab.config": run_config,
    "lab.record": run_record_case,
    "lab.diff": run_diff,
}


def vector_files(root: Path = LAB) -> list[Path]:
    """Every vector file this package is responsible for running."""
    return sorted(root.glob("*.json")) if root.is_dir() else []


def runnerless_vector_files(root: Path = LAB) -> dict[str, str]:
    """Vector files (file name -> suite) with no runner in this package."""
    return {
        path.name: suite
        for path in vector_files(root)
        if (suite := json.loads(path.read_text(encoding="utf-8"))["suite"]) not in RUNNERS
    }


def collect() -> list[Any]:
    params = []
    for path in vector_files():
        doc = json.loads(path.read_text(encoding="utf-8"))
        suite = doc["suite"]
        for case in doc["cases"]:
            params.append(pytest.param(suite, case, id=f"{suite}::{case['name']}"))
    return params


def test_vector_files_are_found() -> None:
    assert vector_files(), f"no lab vector files under {LAB}"


def test_every_lab_vector_file_has_a_runner() -> None:
    unknown = runnerless_vector_files()
    assert not unknown, f"lab vector files with no Python runner: {unknown}"


def test_the_member_order_check_reaches_a_nested_object() -> None:
    """The check biting below the top level, demonstrated rather than assumed."""
    document = {"a": 1, "environment": {"platform": "p", "go": "1.23"}}
    assert_member_order(document, {"a": 1, "environment": {"platform": "p", "go": "1.23"}})
    with pytest.raises(AssertionError, match=r"member order at <root>\.environment"):
        assert_member_order(document, {"a": 1, "environment": {"go": "1.23", "platform": "p"}})


def test_the_member_order_check_descends_into_an_array_of_objects() -> None:
    """Arrays are descended into, with the index in the path.

    Nothing in `record.json` is shaped like this; `diff.json` is -- its
    `expect.differences` is an array of objects -- and a helper that skipped
    arrays would hand that suite a case that cannot fail.
    """
    document = {"cases": [{"a": 1}, {"b": 2, "c": 3}]}
    assert_member_order(document, {"cases": [{"a": 1}, {"b": 2, "c": 3}]})
    with pytest.raises(AssertionError, match=r"member order at <root>\.cases\[1\]"):
        assert_member_order(document, {"cases": [{"a": 1}, {"c": 3, "b": 2}]})
    with pytest.raises(AssertionError, match=r"array length at <root>\.cases"):
        assert_member_order(document, {"cases": [{"a": 1}]})


def test_the_member_order_check_descends_into_an_object_inside_an_array_element() -> None:
    """One more level than the test above, which `lab.diff` reaches.

    A difference whose `recorded` is 8.2's `{"nonfinite": ...}` wrapper is an
    object nested inside an array element, so the recursion has to keep going
    rather than stop at the element itself. The path names both steps.
    """
    document = {"differences": [{"key": "loss", "recorded": {"nonfinite": "NaN"}}]}
    assert_member_order(document, {"differences": [{"key": "loss", "recorded": {"nonfinite": "NaN"}}]})
    with pytest.raises(
        AssertionError, match=r"member order at <root>\.differences\[0\]\.recorded"
    ):
        assert_member_order(
            document, {"differences": [{"key": "loss", "recorded": {"NaN": "nonfinite"}}]}
        )


def test_the_member_order_check_refuses_a_value_of_the_wrong_kind() -> None:
    """A scalar where an object was expected fails rather than being skipped."""
    with pytest.raises(AssertionError, match=r"expected an object at <root>\.environment"):
        assert_member_order({"environment": "macOS"}, {"environment": {"platform": "macOS"}})
    with pytest.raises(AssertionError, match=r"expected an array at <root>\.frameworks"):
        assert_member_order({"frameworks": {}}, {"frameworks": []})
    with pytest.raises(AssertionError, match=r"expected an object at <root>"):
        assert_member_order("not a document", {"run_id": "r"})
    # A string is not an array, however sequence-like it is.
    with pytest.raises(AssertionError, match=r"expected an array at <root>\.tags"):
        assert_member_order({"tags": "ab"}, {"tags": ["a", "b"]})


def test_a_runnerless_lab_file_fails(tmp_path: Path) -> None:
    (tmp_path / "later.json").write_text(
        json.dumps({"suite": "lab.later", "cases": []}), encoding="utf-8"
    )
    assert runnerless_vector_files(tmp_path) == {"later.json": "lab.later"}


def test_every_runner_has_a_vector_file() -> None:
    present = {json.loads(p.read_text(encoding="utf-8"))["suite"] for p in vector_files()}
    assert set(RUNNERS) <= present, set(RUNNERS) - present


@pytest.mark.parametrize(("suite", "case"), collect())
def test_vector(suite: str, case: Case, tmp_path: Path) -> None:
    runner = RUNNERS.get(suite)
    if runner is None:
        pytest.fail(f"no runner for suite {suite!r}")
    runner(case, tmp_path)
