"""Packaging tests for the `hephkit-lab` distribution.

These pin the packaging decisions of ADR 0023: the spine imports with no
scientific stack, it composes with `hephkit` in one PEP 420 namespace
(ADR 0021), its required dependencies stay down to `hephkit` and pydantic, and
its PEP 561 marker sits where -- and only where -- this distribution owns it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SRC = ROOT / "src"

# The stacks the extras exist to keep out of a plain `pip install hephkit-lab`.
# Every one of ADR 0023's nine extras is represented, by TOP-LEVEL IMPORT NAME
# rather than distribution name -- a name no interpreter can ever hold would
# make its entry a silent no-op. `causal-learn` imports as `causallearn` and
# `ligase-bio` as `ligase`; both were read off the installed distributions.
# `accelerate`, `safetensors` and `causalphylo` are omitted only because they
# cannot arrive without `torch`/`transformers` and `causallearn` being imported
# too. This tuple must grow with the extras (ADR 0023).
HEAVY = (
    "torch",  # ml
    "transformers",  # ml
    "mlflow",  # track
    "dowhy",  # causal
    "causallearn",  # causal
    "scipy",  # stats
    "dvc",  # data
    "polars",  # data
    "duckdb",  # data
    "prefect",  # flows
    "marimo",  # notebook
    "ligase",  # bio
)

# `[project].dependencies`, exactly. Specifiers included, not just names: a
# names-only assertion passes with any floor, and a floor that no published
# `hephkit` satisfies is what made the first lockfile stale.
REQUIRED_DEPENDENCIES = {"hephkit>=0.2", "pydantic>=2.9"}


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

    The multi-entry assertion is specific to the **development** install shape
    this repository uses -- two editable portions, each on its own `.pth`, which
    is also the shape design section 7.1.3's typing finding was established
    against. A merged non-editable `pip install` puts both portions in one
    `site-packages/hephkit/`, where `__path__` correctly holds a single entry;
    the assertion would misfire there even though the namespace composes fine.
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
    """`[project].dependencies` is exactly `hephkit` and pydantic, floors included."""
    project = _load_pyproject()["project"]
    assert isinstance(project, dict)
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    assert {str(d) for d in dependencies} == REQUIRED_DEPENDENCIES


def test_the_typing_marker_is_inside_the_subpackage_we_own() -> None:
    """ADR 0021's marker rule, which no other check in the repository enforces.

    `[tool.hatch.build.targets.wheel]`'s `only-include` stops a stray file
    reaching a wheel, but nothing stops one being deleted or added in the tree,
    and `hephkit-lab:typecheck` cannot see either: `[tool.mypy]`'s `mypy_path`
    makes mypy read `src/` as source, where a PEP 561 marker is irrelevant.
    Deleting `src/hephkit/lab/py.typed` would therefore stay green here and
    silently degrade every external consumer of `hephkit.lab` to `Any`.
    """
    assert (SRC / "hephkit" / "lab" / "py.typed").is_file(), (
        "src/hephkit/lab/py.typed is missing: external consumers of hephkit.lab "
        "degrade to Any without it (ADR 0021)"
    )
    assert not (SRC / "hephkit" / "py.typed").exists(), (
        "src/hephkit/py.typed must not exist: the `hephkit` distribution owns "
        "that path, and two distributions owning one file is the collision "
        "ADR 0021 exists to prevent"
    )
    assert not (SRC / "hephkit" / "__init__.py").exists(), (
        "src/hephkit/__init__.py must not exist: it would make `hephkit` a "
        "regular package again and shadow the other portion (ADR 0021)"
    )
