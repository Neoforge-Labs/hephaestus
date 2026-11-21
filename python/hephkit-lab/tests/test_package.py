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


def lab_modules(source: Path = SRC) -> tuple[str, ...]:
    """Every module and subpackage of `hephkit.lab`, as dotted names.

    Walked off the directory rather than listed, and this is the reason: nothing
    else in the suite imports a submodule by name. `hephkit/lab/__init__.py`
    re-exports nothing (ADR 0021), so a module nobody imported in a test would
    be covered by nothing at all, and a module-scope `import scipy` in it would
    land with every check green -- which is the one way the spine guarantee of
    ADR 0023 can be broken silently. A hardcoded tuple only covers the modules
    whoever last edited it remembered.

    Private modules are included on purpose: `_extras` is imported by the rest,
    and a heavy import in it would be just as fatal.
    """
    root = source / "hephkit" / "lab"
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        parts = relative.with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
            if not parts:  # `hephkit.lab` itself, imported by every test already
                continue
        found.append(".".join(("hephkit", "lab", *parts)))
    return tuple(found)


# Every module this distribution adds on top of the spine, each imported by name.
# `hephkit.lab.data` is a package whose `__init__` imports its submodules, and it
# is named here in its own right, so a heavy import in any of them is caught even
# if the `__init__` is later changed to stop importing it.
LAB_MODULES = lab_modules()


def test_the_module_walk_finds_the_package_and_nothing_outside_it() -> None:
    """The derived list is what the two import tests stand on, so pin its shape."""
    assert "hephkit.lab.data" in LAB_MODULES, LAB_MODULES
    assert "hephkit.lab.data.manifest" in LAB_MODULES, LAB_MODULES
    assert "hephkit.lab.stats" in LAB_MODULES, LAB_MODULES
    assert "hephkit.lab._extras" in LAB_MODULES, LAB_MODULES
    # The namespace portion's own `__init__` is not a module to import by name,
    # and nothing outside `hephkit.lab` is in range.
    assert "hephkit.lab" not in LAB_MODULES
    assert all(name.startswith("hephkit.lab.") for name in LAB_MODULES), LAB_MODULES
    # One entry per .py file under the package, minus the package's own __init__.
    files = list((SRC / "hephkit" / "lab").rglob("*.py"))
    assert len(LAB_MODULES) == len(files) - 1, (LAB_MODULES, files)

# What the extras bring in beyond `HEAVY`: NumPy (the `stats` bootstrap) and
# PyArrow (DuckDB's bridge to polars). Neither is an extra of its own, so
# neither is in `HEAVY`, and each must stay behind a function call too.
LAZY = (*HEAVY, "numpy", "pyarrow")


def _run(program: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )


def test_every_lab_module_imports_without_loading_a_heavy_stack() -> None:
    """Importing each module must neither fail nor load anything an extra provides.

    Both failure modes of a module-scope `import polars` / `dvc` / `scipy` are
    covered, whichever environment this runs in. Where the extra is installed the
    import succeeds and the stack appears in `sys.modules`, which the assertion
    reports; where it is not (the spine run), the import itself raises and the
    return code does.
    """
    program = (
        "import importlib, json, sys\n"
        f"for name in {LAB_MODULES!r}:\n"
        "    importlib.import_module(name)\n"
        f"print(json.dumps(sorted(m for m in {LAZY!r} if m in sys.modules)))\n"
    )
    result = _run(program)
    assert result.returncode == 0, f"importing a lab module failed:\n{result.stderr}"
    assert json.loads(result.stdout) == []


_ABSENT_EXTRAS = f"""
import importlib, sys
for name in {LAZY!r}:
    sys.modules[name] = None  # `import name` now raises ModuleNotFoundError
for name in {LAB_MODULES!r}:
    importlib.import_module(name)

from datetime import date
from pathlib import Path

from hephkit.lab._extras import MissingExtraError
from hephkit.lab.data import FileDigest, Manifest, pull, push, query, read_frame
from hephkit.lab.stats import aggregate_seeds, bootstrap_ci

manifest = Manifest(
    dataset="d", source="s", release="r", extractor_version="1", captured_at=date(2026, 1, 1),
    files=(FileDigest(path="a.csv", sha256="0" * 64, bytes=0),),
)
# Every public function that reaches for an extra, all six of them. A caller
# that gets a bare ModuleNotFoundError instead of this is told to fix the wrong
# thing, so each entry point needs its own line here.
calls = {{
    "read_frame": lambda: read_frame(manifest, root=Path(".")),
    "query": lambda: query(manifest, root=Path("."), sql="select 1"),
    "push": lambda: push(manifest, root=Path("."), remote="."),
    "pull": lambda: pull(manifest, into=Path("."), remote="."),
    "bootstrap_ci": lambda: bootstrap_ci([1.0, 2.0, 4.0], seed=0),
    # Reaches the extra through bootstrap_ci, which is exactly why it is here:
    # its own validation must not refuse first and hide that.
    "aggregate_seeds": lambda: aggregate_seeds({{0: 1.0, 1: 2.0, 2: 4.0}}, seed=0),
}}
named = {{}}
for label, call in calls.items():
    try:
        call()
    except MissingExtraError as exc:
        named[label] = str(exc)
assert sorted(named) == sorted(calls), f"these did not raise MissingExtraError: {{named}}"
for label in ("read_frame", "query", "push", "pull"):
    assert "hephkit-lab[data]" in named[label], named[label]
for label in ("bootstrap_ci", "aggregate_seeds"):
    assert "hephkit-lab[stats]" in named[label], named[label]
"""


def test_every_lab_module_imports_with_the_extras_absent() -> None:
    """The same import with the extras forbidden outright, and each use of one refused by name.

    `sys.modules[name] = None` makes `import name` raise, so this holds the line in
    an environment where the extras ARE installed, which is the one the coverage
    gate runs in. A heavy import moved to module scope makes the import loop
    raise; a function that reaches for an extra without `require` raises
    something other than `MissingExtraError`; and a message that stopped naming
    the extra fails the closing assertions.
    """
    result = _run(_ABSENT_EXTRAS)
    assert result.returncode == 0, f"an extra was reached for, or not named:\n{result.stderr}"
