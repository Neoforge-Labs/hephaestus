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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import env_rules
import pytest
import test_repro
from pydantic import ValidationError, create_model

from hephkit.lab.config import ConfigError, ExperimentConfig, config_hash, resolve
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
    assert list(serialised) == list(expect["serialised"]), "member order"


def run_record_case(case: Case, tmp_path: Path) -> None:
    """One `lab.record` case: a capture, or a record document."""
    if "capture" in case["input"]:
        run_capture(case, tmp_path)
    else:
        run_record(case, tmp_path)


RUNNERS: dict[str, Callable[[Case, Path], None]] = {
    "lab.config": run_config,
    "lab.record": run_record_case,
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
