# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Validate spec/errors.yaml, conventions/attributes.yaml and spec/currencies.yaml.

Run with ``uv run tools/check_registry.py`` (PyYAML is declared inline, PEP 723).

Error entries need ``{code, status, title, area, detail_hint}``: the code matches
``HEPH-[A-Z]{2,6}-[0-9]{3}`` (full match, ASCII digits), is unique, ``status`` is 400-599 and ``area`` equals
the code's middle segment. Attribute entries need ``{name, type, description,
pii}``: names are dotted lowercase, unique, and ``pii`` is a real boolean.
Currency entries need ``{code, numeric, name, minor_units}``: the code is three
uppercase ASCII letters, entries are unique and in ascending code order, and
``minor_units`` is either an integer 0-4 or the string ``N.A.`` exactly as ISO
4217 List One publishes it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

CODE_RE = re.compile(r"HEPH-[A-Z]{2,6}-[0-9]{3}")
ATTR_RE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")
CCY_RE = re.compile(r"[A-Z]{3}")
CCY_NBR_RE = re.compile(r"[0-9]{3}")
ERROR_FIELDS = ("code", "status", "title", "area", "detail_hint")
ATTRIBUTE_FIELDS = ("name", "type", "description", "pii")
CURRENCY_FIELDS = ("code", "numeric", "name", "minor_units")
# ISO 4217 publishes no exponent above 4 (CLF and UYW); Currency.exponent is a u8.
MAX_EXPONENT = 4
NO_EXPONENT = "N.A."


def _load(path: Path, errors: list[str]) -> list[Any]:
    if not path.is_file():
        errors.append(f"{path} does not exist")
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{path.name}: cannot read file: {exc}")
        return []
    except yaml.YAMLError as exc:
        errors.append(f"{path.name}: invalid YAML: {exc}")
        return []
    if not isinstance(data, list):
        errors.append(f"{path.name}: top level must be a list of entries")
        return []
    return data


def _check_errors(path: Path, errors: list[str]) -> None:
    seen: set[str] = set()
    for entry in _load(path, errors):
        if not isinstance(entry, dict):
            errors.append(f"{path.name}: entry is not a mapping: {entry!r}")
            continue
        code = str(entry.get("code", "<missing>"))
        for field in ERROR_FIELDS:
            if entry.get(field) in (None, ""):
                errors.append(f"{path.name}: {code}: missing '{field}'")
        if not CODE_RE.fullmatch(code):
            errors.append(f"{path.name}: {code}: code must match {CODE_RE.pattern}")
        else:
            if entry.get("area") != code.split("-")[1]:
                errors.append(f"{path.name}: {code}: area must equal '{code.split('-')[1]}'")
        if code in seen:
            errors.append(f"{path.name}: duplicate code {code}")
        seen.add(code)
        status = entry.get("status")
        if not isinstance(status, int) or isinstance(status, bool) or not 400 <= status <= 599:
            errors.append(f"{path.name}: {code}: status must be an integer 400-599")


def _check_attributes(path: Path, errors: list[str]) -> None:
    seen: set[str] = set()
    for entry in _load(path, errors):
        if not isinstance(entry, dict):
            errors.append(f"{path.name}: entry is not a mapping: {entry!r}")
            continue
        name = str(entry.get("name", "<missing>"))
        for field in ATTRIBUTE_FIELDS:
            if entry.get(field) in (None, ""):
                errors.append(f"{path.name}: {name}: missing '{field}'")
        if not ATTR_RE.fullmatch(name):
            errors.append(f"{path.name}: {name}: name must be dotted lowercase")
        if name in seen:
            errors.append(f"{path.name}: duplicate attribute {name}")
        seen.add(name)
        if not isinstance(entry.get("pii"), bool):
            errors.append(f"{path.name}: {name}: pii must be a boolean")


def _check_currencies(path: Path, errors: list[str]) -> None:
    seen: set[str] = set()
    numbers: set[str] = set()
    previous = ""
    for entry in _load(path, errors):
        if not isinstance(entry, dict):
            errors.append(f"{path.name}: entry is not a mapping: {entry!r}")
            continue
        code = str(entry.get("code", "<missing>"))
        for field in CURRENCY_FIELDS:
            if entry.get(field) in (None, ""):
                errors.append(f"{path.name}: {code}: missing '{field}'")
        if not CCY_RE.fullmatch(code):
            errors.append(f"{path.name}: {code}: code must be three uppercase ASCII letters")
        if code in seen:
            errors.append(f"{path.name}: duplicate code {code}")
        elif code < previous:
            errors.append(f"{path.name}: {code} is out of order (after {previous}); entries are sorted by code")
        seen.add(code)
        previous = code
        numeric = entry.get("numeric")
        if not isinstance(numeric, str) or not CCY_NBR_RE.fullmatch(numeric):
            errors.append(f"{path.name}: {code}: numeric must be a quoted three-digit string")
        elif numeric in numbers:
            errors.append(f"{path.name}: {code}: duplicate numeric code {numeric}")
        else:
            numbers.add(numeric)
        units = entry.get("minor_units")
        if isinstance(units, bool) or not (
            (isinstance(units, int) and 0 <= units <= MAX_EXPONENT) or units == NO_EXPONENT
        ):
            errors.append(
                f"{path.name}: {code}: minor_units must be an integer 0-{MAX_EXPONENT} "
                f"or the string {NO_EXPONENT!r}, as List One publishes it"
            )


def check_errors(path: Path) -> list[str]:
    """Return a list of error strings for the error registry alone."""
    found: list[str] = []
    _check_errors(path, found)
    return found


def check_attributes(path: Path) -> list[str]:
    """Return a list of error strings for the attribute registry alone."""
    found: list[str] = []
    _check_attributes(path, found)
    return found


def check_currencies(path: Path) -> list[str]:
    """Return a list of error strings for the currency registry alone."""
    found: list[str] = []
    _check_currencies(path, found)
    return found


def check_registry(errors: Path, attributes: Path, currencies: Path | None = None) -> list[str]:
    """Return a list of error strings for the registry files.

    ``currencies`` is optional so a caller can check the two older registries
    on their own; ``main`` always passes all three.
    """
    found: list[str] = []
    _check_errors(errors, found)
    _check_attributes(attributes, found)
    if currencies is not None:
        _check_currencies(currencies, found)
    return found


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    found = check_registry(
        root / "spec" / "errors.yaml",
        root / "conventions" / "attributes.yaml",
        root / "spec" / "currencies.yaml",
    )
    for error in found:
        print(error, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
