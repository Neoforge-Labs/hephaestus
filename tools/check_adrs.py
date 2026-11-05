"""Check that docs/adr/ holds well-formed, contiguously numbered ADRs.

Every ``docs/adr/NNNN-*.md`` must have a four-digit prefix, numbers must be
contiguous from 0001, and each file needs the Status, Context, Decision and
Consequences headings. ``0000-template.md`` is a template, not a decision, and
is skipped.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_HEADINGS = ("## Status", "## Context", "## Decision", "## Consequences")
TEMPLATE_NAME = "0000-template.md"
_NUMBERED = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.md$")


def check_adrs(root: Path) -> list[str]:
    """Return a list of error strings for the ADRs under ``root/docs/adr``."""
    adr_dir = root / "docs" / "adr"
    if not adr_dir.is_dir():
        return [f"{adr_dir} does not exist"]

    errors: list[str] = []
    numbers: list[int] = []
    for path in sorted(adr_dir.glob("*.md")):
        if path.name == TEMPLATE_NAME:
            continue
        match = _NUMBERED.match(path.name)
        if not match:
            errors.append(f"{path.name}: name must match NNNN-kebab-title.md")
            continue
        numbers.append(int(match.group(1)))
        lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
        for heading in REQUIRED_HEADINGS:
            if heading not in lines:
                errors.append(f"{path.name}: missing heading '{heading}'")

    seen: set[int] = set()
    for n in numbers:
        if n in seen:
            errors.append(f"duplicate ADR number {n:04d}")
        seen.add(n)
    if seen:
        for expected in range(1, max(seen) + 1):
            if expected not in seen:
                errors.append(f"missing ADR {expected:04d}: numbers must be contiguous from 0001")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = check_adrs(root)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
