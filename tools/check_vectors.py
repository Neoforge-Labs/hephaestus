# /// script
# requires-python = ">=3.12"
# dependencies = ["jsonschema", "pyyaml"]
# ///
"""Validate the conformance vector files under conformance/.

Run with ``uv run tools/check_vectors.py`` (jsonschema and PyYAML are declared
inline, PEP 723). Every ``conformance/<area>/<suite>.json`` must satisfy
``conformance/schema/vector-file.schema.json``, its ``suite`` must equal
``<area>.<suite>`` from the file name, case names must be unique, every
``{"error": code}`` must name a code in ``spec/errors.yaml``, and every suite
must be present with at least its minimum number of cases.

This checker only validates files. It never produces a vector and never runs
any Hephaestus implementation (CLAUDE.md rule 2).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

MIN_CASES = {
    "money.currency": 12,
    "money.parse": 30,
    "money.format": 10,
    "money.arith": 8,
    "money.compare": 20,
    "money.allocate": 10,
    "hashing.jcs": 12,
    "hashing.content": 6,
    "signatures.sign": 4,
    "signatures.verify": 10,
}


def _registry(path: Path, found: list[str]) -> set[str]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return {e["code"] for e in data}
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError, KeyError) as exc:
        found.append(f"{path.name}: cannot read error registry: {exc}")
        return set()


def check_vectors(conformance: Path, errors_yaml: Path, require_all: bool = True) -> list[str]:
    """Return a list of error strings for the vector files under ``conformance``."""
    found: list[str] = []
    schema_path = conformance / "schema" / "vector-file.schema.json"
    try:
        validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        return [f"{schema_path}: cannot load schema: {exc}"]
    codes = _registry(errors_yaml, found)

    seen: set[str] = set()
    for path in sorted(conformance.glob("*/*.json")):
        if path.parent.name == "schema":
            continue
        label = path.relative_to(conformance).as_posix()
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            found.append(f"{label}: cannot read: {exc}")
            continue
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
            where = "/".join(str(p) for p in err.absolute_path) or "<root>"
            found.append(f"{label}: {where}: {err.message[:200]}")
        if not isinstance(data, dict):
            continue
        suite = data.get("suite")
        expected = f"{path.parent.name}.{path.stem}"
        if suite != expected:
            found.append(f"{label}: suite {suite!r} must equal {expected!r} (from the file name)")
            continue
        seen.add(expected)
        names: set[str] = set()
        cases = data.get("cases")
        for case in cases if isinstance(cases, list) else []:
            if not isinstance(case, dict):
                continue
            name = case.get("name")
            if name in names:
                found.append(f"{label}: duplicate case name {name!r}")
            names.add(str(name))
            expect = case.get("expect")
            code = expect.get("error") if isinstance(expect, dict) else None
            if isinstance(code, str) and codes and code not in codes:
                found.append(f"{label}: {name}: {code} is not in the error registry")
        if require_all and isinstance(cases, list) and len(cases) < MIN_CASES.get(expected, 0):
            found.append(f"{label}: {len(cases)} cases, minimum is {MIN_CASES[expected]}")
    if require_all:
        for suite in MIN_CASES:
            if suite not in seen:
                found.append(f"{suite.replace('.', '/')}.json: missing suite file")
    return found


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    found = check_vectors(root / "conformance", root / "spec" / "errors.yaml")
    for error in found:
        print(error, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
