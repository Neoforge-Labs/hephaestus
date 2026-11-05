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
"""

from __future__ import annotations

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

# Directories that sit where modules live but are not modules themselves.
NOT_MODULES = {
    "rust": {"fuzz": "fuzz-target harness, not a module", "target": "cargo build output"},
    "docker": {"test": "test harness, not a runtime image"},
}
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

    compose = repo_root / "compose"
    if compose.is_dir():
        for p in compose.glob("*.yaml"):
            found.add(("compose", p.stem))
    return found


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


def _compose_header_maturity(path: Path) -> str | None:
    first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    match = HEADER_MATURITY_RE.search(first) if first.startswith("#") else None
    return match.group(1) if match else None


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

    for home, name in sorted(_scan(repo_root)):
        entry = by_key.get((home, name))
        if entry is None or entry.get("status") != "shipped":
            errors.append(f"modules.yaml: {home}/{name} exists on disk but has no shipped entry")
        elif home == "compose":
            header = _compose_header_maturity(repo_root / "compose" / f"{name}.yaml")
            if header != entry.get("maturity"):
                errors.append(
                    f"modules.yaml: {name}: compose header says maturity {header!r}, "
                    f"entry says {entry.get('maturity')!r}"
                )
    return errors


def main() -> int:
    errors = check_modules(Path(__file__).resolve().parents[1])
    for e in errors:
        print(e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
