# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Generate the core's ISO 4217 exponent table from spec/currencies.yaml.

Run with ``uv run tools/gen_currencies.py`` to write the file, or with
``--check`` to exit 1 if the committed file differs from what the registry would
generate. PyYAML is declared inline (PEP 723). The registry is validated first;
an invalid registry writes nothing.

A code reaches the table if and only if its List One minor-unit field is numeric
(ADR 0017). Codes the standard publishes as ``N.A.`` stay out and are rejected
with ``HEPH-MONEY-422``; so is any code the standard has retired from List One.
This script never consults a heph implementation for an exponent (CLAUDE.md
rule 2): spec/currencies.yaml is a transcription of the standard, and is the
only input.

The output is a pure function of the registry: entries are ordered by code and
there are no timestamps, so two runs give identical bytes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from check_registry import check_currencies

OUTPUT_RELPATH = Path("core/hephkit-core/src/money/currency_table.rs")
REGISTRY_RELPATH = Path("spec/currencies.yaml")

HEADER = """\
//! ISO 4217 minor-unit exponents generated from spec/currencies.yaml.
//!
//! GENERATED FILE - do not edit by hand. Regenerate with
//! `uv run tools/gen_currencies.py`; CI runs `--check`. Exponents live only in
//! `spec/currencies.yaml`, which transcribes ISO 4217 List One as published by
//! SIX Group. Editing a number here would make the core disagree with the
//! standard and with every other binding.
//!
//! A code appears below if and only if its List One minor-unit field is
//! numeric (ADR 0017), so the funds codes are in and the codes published as
//! `N.A.` are out. Lookup of a code that is absent is `HEPH-MONEY-422`.
//!
//! Entries are ordered by code, which `Currency::from_code` relies on to
//! binary search; `money::currency` tests that invariant.

/// Every ISO 4217 code with a defined minor-unit exponent, ordered by code.
"""


def render(entries: list[dict[str, Any]]) -> str:
    """The text of ``currency_table.rs`` for validated registry entries."""
    accepted = sorted(
        (str(e["code"]), int(e["minor_units"]))
        for e in entries
        if isinstance(e["minor_units"], int) and not isinstance(e["minor_units"], bool)
    )
    lines = [HEADER]
    lines.append(f"pub(super) const TABLE: [([u8; 3], u8); {len(accepted)}] = [\n")
    for code, exponent in accepted:
        lines.append(f'    (*b"{code}", {exponent}),\n')
    lines.append("];\n")
    return "".join(lines)


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    check = "--check" in args
    unknown = [a for a in args if a != "--check"]
    if unknown:
        print(f"usage: gen_currencies.py [--check] (unknown: {' '.join(unknown)})", file=sys.stderr)
        return 2
    root = root or Path(__file__).resolve().parents[1]
    registry = root / REGISTRY_RELPATH
    output = root / OUTPUT_RELPATH

    problems = check_currencies(registry)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    entries = yaml.safe_load(registry.read_text(encoding="utf-8"))
    text = render(entries)

    if check:
        current = output.read_text(encoding="utf-8") if output.is_file() else None
        if current != text:
            print(f"{OUTPUT_RELPATH} is stale or missing; run: uv run tools/gen_currencies.py", file=sys.stderr)
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
