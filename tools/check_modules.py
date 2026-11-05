# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Validate spec/modules.yaml, the module inventory behind the docs ledger.

Run with ``uv run --with pyyaml python tools/check_modules.py`` (PyYAML is
declared inline, PEP 723).

Entries need ``name``, ``home`` (rust|python|go|ts|compose|docker), ``status``
(shipped|planned) and ``spec_section`` (a section number of spec/heph-spec.md
as a string, or null). ``maturity`` (experimental|beta|stable) is required
exactly when ``status`` is ``shipped``; ``phase`` (an integer) exactly when it
is ``planned``. Every module found on disk must have a ``shipped`` entry, a
Compose fragment's ``maturity:`` header comment must agree with its entry, and
at least one entry must be ``planned`` so the ledger has both sides. Directories
that do not exist contribute no required entries.

A ``shipped`` rust, python or go module must also carry ``Maturity: <level>`` in
its source documentation, matching its entry: the crate's ``//!`` doc comment
(``src/lib.rs``, else ``src/main.rs``), the module docstring (``<name>.py`` or
``<name>/__init__.py``), or a Go package comment (the comment block directly
above ``package`` in any non-test file, as in ``go/internal/ingot/config.go``).
``docker`` images are not checked: a Dockerfile has no doc-comment convention
and none has been decided.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

import yaml

HOMES = ("rust", "python", "go", "ts", "compose", "docker")
STATUSES = ("shipped", "planned")
MATURITIES = ("experimental", "beta", "stable")
SECTION_RE = re.compile(r"^## (\d+)\. ", re.MULTILINE)
HEADER_MATURITY_RE = re.compile(r"maturity:\s*([a-z]+)\s*$")
# The in-source label. Case-sensitive on purpose: ``Maturity: Experimental`` is a mismatch.
LABEL_RE = re.compile(r"\bMaturity:\s*([A-Za-z]+)")
# Shipped rows whose source must carry a label. ``docker`` is deliberately absent: a Dockerfile
# has no doc-comment convention and inventing one is an undecided design question.
LABELLED_HOMES = ("rust", "python", "go")

# Directories that sit where modules live but are not modules themselves.
NOT_MODULES = {
    "rust": {"fuzz": "fuzz-target harness, not a module", "target": "cargo build output"},
    "docker": {"test": "test harness, not a runtime image"},
}
# Files under compose/ that are not fragments and so carry no maturity header.
NOT_FRAGMENTS = {"moon.yml": "moon project config, not a Compose fragment"}
# Generated, not a module of its own.
PYTHON_EXCLUDED_FILES = {"conventions.py"}


def _scan(repo_root: Path) -> set[tuple[str, str]]:
    """Return the (home, name) of every module present on disk."""
    found: set[tuple[str, str]] = set()

    py = repo_root / "python" / "hephkit" / "src" / "hephkit"
    if py.is_dir():
        for p in py.iterdir():
            if p.name.startswith("_") or p.name in PYTHON_EXCLUDED_FILES:
                continue
            if p.is_dir():
                found.add(("python", p.name))
            elif p.suffix == ".py":
                found.add(("python", p.stem))

    def dirs(rel: str, home: str, key: str | None = None) -> None:
        base = repo_root / rel
        if base.is_dir():
            skip = NOT_MODULES.get(key or home, {})
            for p in base.iterdir():
                if p.is_dir() and p.name not in skip:
                    found.add((home, p.name))

    dirs("core", "rust")
    dirs("go/internal", "go")
    dirs("go/cmd", "go")
    dirs("docker", "docker")

    return found


def _compose_fragments(repo_root: Path) -> tuple[dict[str, Path], list[str]]:
    """Find Compose fragments by content, not extension.

    A fragment is a ``compose/*.yaml`` or ``*.yml`` file that parses as a mapping
    with a top-level ``services:`` key. A file that is neither a fragment nor a
    known tooling file is reported, not skipped, so it cannot escape the check.
    """
    fragments: dict[str, Path] = {}
    errors: list[str] = []
    compose = repo_root / "compose"
    if not compose.is_dir():
        return fragments, errors
    for p in sorted([*compose.glob("*.yaml"), *compose.glob("*.yml")]):
        if not p.is_file() or p.name in NOT_FRAGMENTS:
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"modules.yaml: {p.stem}: cannot read compose fragment {p.name}: {exc}")
            continue
        except yaml.YAMLError as exc:
            errors.append(f"modules.yaml: compose/{p.name} is not valid YAML, so it cannot be checked as a fragment: {exc}")
            continue
        if isinstance(data, dict) and "services" in data:
            if p.stem in fragments:
                errors.append(f"modules.yaml: compose/{p.name} and compose/{fragments[p.stem].name} share the name {p.stem}")
            fragments[p.stem] = p
        else:
            errors.append(
                f"modules.yaml: compose/{p.name} has no top-level 'services:' key and is not a known "
                "tooling file, so it is not recognised as a fragment; fix it or add it to NOT_FRAGMENTS"
            )
    return fragments, errors


def _validate_entry(entry: Any, sections: set[str]) -> tuple[str, list[str]]:
    if not isinstance(entry, dict):
        return "<invalid>", [f"modules.yaml: entry is not a mapping: {entry!r}"]
    name = str(entry.get("name", "<missing>"))
    errs: list[str] = []

    def err(msg: str) -> None:
        errs.append(f"modules.yaml: {name}: {msg}")

    if entry.get("name") in (None, ""):
        err("missing 'name'")
    if entry.get("home") not in HOMES:
        err(f"home must be one of {', '.join(HOMES)}")
    status = entry.get("status")
    if status not in STATUSES:
        err(f"status must be one of {', '.join(STATUSES)}")
    maturity = entry.get("maturity")
    phase = entry.get("phase")
    if status == "shipped":
        if maturity not in MATURITIES:
            err(f"shipped module needs maturity, one of {', '.join(MATURITIES)}")
        if phase is not None:
            err("shipped module must not have a phase")
    elif status == "planned":
        if maturity is not None:
            err("planned module must not have a maturity")
        if not isinstance(phase, int) or isinstance(phase, bool):
            err("planned module needs an integer phase")
    if "spec_section" not in entry:
        err("missing 'spec_section' (use null for none)")
    else:
        section = entry["spec_section"]
        if section is not None and (not isinstance(section, str) or section not in sections):
            err(f"spec_section {section!r} does not match a section of heph-spec.md")
    return name, errs


def _compose_header_maturity(path: Path) -> tuple[str | None, str | None]:
    """The fragment's header maturity and, if it could not be read, an error message."""
    try:
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"modules.yaml: {path.stem}: cannot read compose fragment {path.name}: {exc}"
    match = HEADER_MATURITY_RE.search(first) if first.startswith("#") else None
    return (match.group(1) if match else None), None


def _rust_doc(text: str) -> str:
    """The crate's leading ``//!`` inner-doc block, skipping blank lines and plain ``//`` comments."""
    doc: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//!"):
            doc.append(stripped[3:])
        elif doc or (stripped and not stripped.startswith("//")):
            break
    return "\n".join(doc)


def _go_doc(text: str) -> str:
    """The ``//`` comment block directly above the first ``package`` clause (no blank line between)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("package "):
            doc: list[str] = []
            for prev in reversed(lines[:i]):
                if not prev.startswith("//"):
                    break
                doc.append(prev[2:])
            return "\n".join(reversed(doc))
    return ""


def _source_docs(repo_root: Path, home: str, name: str) -> tuple[list[tuple[str, str]], str | None]:
    """The ``(repo-relative path, documentation text)`` pairs that may carry the module's label.

    Returns an error message instead when the source cannot be located or read.
    """
    if home == "rust":
        candidates = [repo_root / "core" / name / "src" / "lib.rs", repo_root / "core" / name / "src" / "main.rs"]
        files = [c for c in candidates if c.is_file()][:1]
    elif home == "python":
        base = repo_root / "python" / "hephkit" / "src" / "hephkit"
        files = [c for c in (base / f"{name}.py", base / name / "__init__.py") if c.is_file()][:1]
    else:
        files = []
        for d in (repo_root / "go" / "internal" / name, repo_root / "go" / "cmd" / name):
            if d.is_dir():
                files.extend(sorted(f for f in d.glob("*.go") if not f.name.endswith("_test.go")))
    if not files:
        return [], f"modules.yaml: {name}: shipped {home} module has no source on disk to carry its Maturity label"
    docs: list[tuple[str, str]] = []
    for f in files:
        rel = f.relative_to(repo_root).as_posix()
        try:
            text = f.read_text(encoding="utf-8")
            if home == "python":
                doc = ast.get_docstring(ast.parse(text)) or ""
            else:
                doc = _rust_doc(text) if home == "rust" else _go_doc(text)
        except (OSError, UnicodeDecodeError) as exc:
            return [], f"modules.yaml: {name}: cannot read {rel}: {exc}"
        except (SyntaxError, ValueError) as exc:
            return [], f"modules.yaml: {name}: cannot parse {rel} to find its module docstring: {exc}"
        docs.append((rel, doc))
    return docs, None


def _check_source_label(repo_root: Path, home: str, name: str, entry: dict) -> list[str]:
    """Errors for one shipped rust/python/go row whose in-source label is missing or disagrees."""
    docs, problem = _source_docs(repo_root, home, name)
    if problem:
        return [problem]
    where = {"rust": "//! crate doc comment", "python": "module docstring", "go": "package comment"}[home]
    expected = entry.get("maturity")
    errors: list[str] = []
    found = False
    for rel, doc in docs:
        match = LABEL_RE.search(doc)
        if match is None:
            continue
        found = True
        if match.group(1) != expected:
            errors.append(
                f"modules.yaml: {name}: maturity mismatch: {rel} {where} says {match.group(1)!r}, "
                f"entry says {expected!r}"
            )
    if not found:
        files = ", ".join(rel for rel, _ in docs)
        errors.append(
            f"modules.yaml: {name}: no Maturity label in the {where} of {files}; "
            f"add 'Maturity: {expected}.' to it (entry says {expected!r})"
        )
    return errors


def check_modules(repo_root: Path) -> list[str]:
    """Return human-readable errors for spec/modules.yaml; empty when valid."""
    path = repo_root / "spec" / "modules.yaml"
    if not path.is_file():
        return [f"{path} does not exist"]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        return [f"modules.yaml: cannot read file: {exc}"]
    except yaml.YAMLError as exc:
        return [f"modules.yaml: invalid YAML: {exc}"]
    if not isinstance(data, list):
        return ["modules.yaml: top level must be a list of entries"]

    spec = repo_root / "spec" / "heph-spec.md"
    sections = set(SECTION_RE.findall(spec.read_text(encoding="utf-8"))) if spec.is_file() else set()

    errors: list[str] = []
    by_key: dict[tuple[str, str], dict] = {}
    for entry in data:
        name, errs = _validate_entry(entry, sections)
        errors.extend(errs)
        if isinstance(entry, dict):
            key = (str(entry.get("home")), name)
            if key in by_key:
                errors.append(f"modules.yaml: duplicate entry {entry.get('home')}/{name}")
            by_key[key] = entry

    if not any(isinstance(e, dict) and e.get("status") == "planned" for e in data):
        errors.append("modules.yaml: no planned entry; the ledger needs both sides")

    fragments, fragment_errors = _compose_fragments(repo_root)
    errors.extend(fragment_errors)
    for home, name in sorted(_scan(repo_root) | {("compose", n) for n in fragments}):
        entry = by_key.get((home, name))
        if entry is None or entry.get("status") != "shipped":
            errors.append(f"modules.yaml: {home}/{name} exists on disk but has no shipped entry")
        elif home == "compose":
            header, unreadable = _compose_header_maturity(fragments[name])
            if unreadable:
                errors.append(unreadable)
            elif header != entry.get("maturity"):
                errors.append(
                    f"modules.yaml: {name}: compose header says maturity {header!r}, "
                    f"entry says {entry.get('maturity')!r}"
                )
    # In-source labels. Driven by the rows, not the scan, so a shipped row whose source is gone is
    # reported too. docker rows are intentionally not checked (see LABELLED_HOMES).
    for (home, name), entry in sorted(by_key.items()):
        if entry.get("status") == "shipped" and home in LABELLED_HOMES and entry.get("maturity") in MATURITIES:
            errors.extend(_check_source_label(repo_root, home, name, entry))
    return errors


def main() -> int:
    errors = check_modules(Path(__file__).resolve().parents[1])
    for e in errors:
        print(e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
