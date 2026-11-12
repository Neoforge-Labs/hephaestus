"""Run the `lab.*` conformance vectors through the Python API.

Vector files are discovered by globbing `conformance/lab/*.json`. A file whose
`suite` has no runner here is a hard failure, never a skip: a new vector file
must not be silently untested. This mirrors
`python/hephkit/tests/test_conformance.py`, which owns every other area and
exempts `lab/` because it must keep zero runtime dependencies.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import create_model

from hephkit.lab.config import ConfigError, ExperimentConfig, config_hash, resolve

ROOT = Path(__file__).resolve().parents[3] / "conformance"
LAB = ROOT / "lab"

Case = dict[str, Any]

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


RUNNERS: dict[str, Callable[[Case, Path], None]] = {
    "lab.config": run_config,
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
