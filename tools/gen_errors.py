# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Generate hephkit.errors._codes from spec/errors.yaml.

Run with ``uv run tools/gen_errors.py`` to write the file, or with ``--check`` to
exit 1 if the committed file differs from what the registry would generate.
PyYAML is declared inline (PEP 723). The registry is validated first; an
invalid registry writes nothing.

The output is a pure function of the registry: entries keep registry order and
there are no timestamps, so two runs give identical bytes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from check_registry import check_errors

OUTPUT_RELPATH = Path("python/hephkit/src/hephkit/errors/_codes.py")
REGISTRY_RELPATH = Path("spec/errors.yaml")

HEADER = '''\
"""Error-code constants generated from spec/errors.yaml.

GENERATED FILE - do not edit by hand. Regenerate with
``uv run tools/gen_errors.py``; CI runs ``--check``. Codes live only in
``spec/errors.yaml``.
"""

from typing import Final

'''


def _constant_name(code: str) -> str:
    return code.removeprefix("HEPH-").replace("-", "_")


def render(entries: list[dict[str, Any]]) -> str:
    """The text of ``_codes.py`` for validated registry entries."""
    lines = [HEADER]
    for entry in entries:
        lines.append(f'{_constant_name(entry["code"])}: Final = {json.dumps(entry["code"])}\n')
    lines.append("\n# code -> (HTTP status, title)\nREGISTRY: dict[str, tuple[int, str]] = {\n")
    for entry in entries:
        lines.append(f'    {json.dumps(entry["code"])}: ({entry["status"]}, {json.dumps(entry["title"])}),\n')
    lines.append("}\n")
    lines.append("\n# code -> guidance for the caller, used as the default problem `detail`\nDETAIL_HINTS: dict[str, str] = {\n")
    for entry in entries:
        lines.append(f'    {json.dumps(entry["code"])}: {json.dumps(entry["detail_hint"])},\n')
    lines.append("}\n")
    return "".join(lines)


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    check = "--check" in args
    unknown = [a for a in args if a != "--check"]
    if unknown:
        print(f"usage: gen_errors.py [--check] (unknown: {' '.join(unknown)})", file=sys.stderr)
        return 2
    root = root or Path(__file__).resolve().parents[1]
    registry = root / REGISTRY_RELPATH
    output = root / OUTPUT_RELPATH

    problems = check_errors(registry)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    entries = yaml.safe_load(registry.read_text(encoding="utf-8"))
    text = render(entries)

    if check:
        current = output.read_text(encoding="utf-8") if output.is_file() else None
        if current != text:
            print(f"{OUTPUT_RELPATH} is stale or missing; run: uv run tools/gen_errors.py", file=sys.stderr)
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
