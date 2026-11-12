"""Packaging tests for the `hephkit-lab` distribution.

These three tests pin the packaging decisions of ADR 0023: the spine imports
with no scientific stack, it composes with `hephkit` in one PEP 420 namespace
(ADR 0021), and its required dependencies stay down to `hephkit` and pydantic.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

# The stacks the extras exist to keep out of a plain `pip install hephkit-lab`.
HEAVY = ("torch", "mlflow", "dowhy", "dvc", "prefect", "polars", "duckdb", "marimo")


def _load_pyproject() -> dict[str, object]:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def test_lab_imports_with_no_scientific_stack() -> None:
    """`import hephkit.lab` must not drag in any of the heavy stacks.

    Run in a subprocess so the assertion is about a clean interpreter rather
    than whatever the pytest session happened to import first.
    """
    program = (
        "import json, sys; import hephkit.lab; "
        f"print(json.dumps(sorted(m for m in {HEAVY!r} if m in sys.modules)))"
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"importing hephkit.lab failed:\n{result.stderr}"
    assert json.loads(result.stdout) == []


def test_core_and_lab_coexist_in_one_namespace() -> None:
    """Both portions of the `hephkit` namespace resolve, and both are present.

    This is the first point in the repository where two distributions supply
    one namespace, so it is the first place ADR 0021's actual property can be
    tested. Asserting only that the imports succeed is not enough: that passes
    when one portion shadows the other. `hephkit.__path__` must be a namespace
    path holding both trees.
    """
    import hephkit

    from hephkit.hashing import content_hash
    from hephkit.lab import __all__ as lab_all

    assert content_hash({}) and isinstance(lab_all, list)

    assert getattr(hephkit, "__file__", None) is None, "hephkit must stay a namespace package"
    portions = list(hephkit.__path__)
    assert len(portions) > 1, f"expected two namespace portions, got {portions!r}"
    assert any("hephkit-lab" in p for p in portions), f"no hephkit-lab portion in {portions!r}"


def test_spine_declares_no_heavy_dependencies() -> None:
    """`[project].dependencies` is exactly `hephkit` and pydantic."""
    project = _load_pyproject()["project"]
    assert isinstance(project, dict)
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    names = {str(d).split(">")[0].split("=")[0].split("[")[0].strip() for d in dependencies}
    assert names == {"hephkit", "pydantic"}, f"unexpected required dependencies: {names}"
