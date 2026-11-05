# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Generate one docs page per error code from spec/errors.yaml.

Run with ``uv run tools/gen_error_pages.py`` to write the pages, or with
``--check`` to exit 1 (naming each file) if a committed page is missing, stale
or has no registry code. PyYAML is declared inline (PEP 723). The registry is
validated first; an invalid registry writes nothing.

Pages live at ``docs/site/content/errors/<code>.mdx`` so the site serves them at
``/errors/<code>``, the URL heph-spec 1.4 requires in every problem ``type``.
The hand-written ``_meta.ts`` beside them orders the sidebar; a test pins its
keys to the registry.

The registry prose is untrusted input to the MDX compiler, so every value is
escaped before it is written. The output is a pure function of the registry:
registry order, no timestamps, so two runs give identical bytes.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from check_registry import check_errors

PAGES_RELDIR = Path("docs/site/content/errors")
REGISTRY_RELDIR = Path("spec/errors.yaml")

# Characters Markdown or MDX would interpret: JSX/expressions ({ } < >), emphasis
# and code (* _ `), links (\[ \]), tables, headings, entities and the escape itself.
_SPECIAL = re.compile(r"([\\`*_{}\[\]<>|#&~^$!])")


def _escape(text: str) -> str:
    """Make registry prose literal in MDX; renders identically to the source."""
    return _SPECIAL.sub(r"\\\1", " ".join(text.split()))


def render(entry: dict[str, Any]) -> str:
    """The text of one page for a validated registry entry."""
    code = entry["code"]
    title = _escape(str(entry["title"]))
    return f"""\
---
# GENERATED FILE - do not edit by hand. Source: spec/errors.yaml.
# Regenerate with `uv run tools/gen_error_pages.py`; CI runs --check.
title: {json.dumps(f"{code} — {entry['title']}", ensure_ascii=False)}
---

# {code}

**{title}**

| | |
| --- | --- |
| HTTP status | `{entry["status"]}` |
| Area | `{entry["area"]}` |
| Problem `type` | `https://heph.neoforgelabs.tech/errors/{code}` |

## What the caller sees

This is the default `detail` sent in the problem+json response, verbatim:

{_escape(str(entry["detail_hint"]))}

## What to do as a developer

Guidance for the engineer who hit this code. It is non-normative: it is never
sent on the wire and does not constrain an implementation. Wire behaviour is
defined only by `spec/heph-spec.md` and the conformance vectors.

{_escape(str(entry["guidance"]))}

---

Defined in `spec/heph-spec.md` section 1. See all codes in the [error reference](/reference/errors).
"""


def generate(repo_root: Path) -> dict[Path, str]:
    """Map each output path to its content, in registry order."""
    registry = repo_root / REGISTRY_RELDIR
    problems = check_errors(registry)
    if problems:
        raise ValueError("\n".join(problems))
    entries = yaml.safe_load(registry.read_text(encoding="utf-8"))
    return {repo_root / PAGES_RELDIR / f"{e['code']}.mdx": render(e) for e in entries}


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    check = "--check" in args
    unknown = [a for a in args if a != "--check"]
    if unknown:
        print(f"usage: gen_error_pages.py [--check] (unknown: {' '.join(unknown)})", file=sys.stderr)
        return 2
    root = root or Path(__file__).resolve().parents[1]

    try:
        pages = generate(root)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1

    if check:
        drift = [
            p for p, text in pages.items() if not p.is_file() or p.read_text(encoding="utf-8") != text
        ]
        directory = root / PAGES_RELDIR
        orphans = [p for p in sorted(directory.glob("HEPH-*.mdx")) if p not in pages] if directory.is_dir() else []
        for path in drift + orphans:
            reason = "has no registry code" if path in orphans else "is stale or missing"
            print(f"{path.relative_to(root)} {reason}; run: uv run tools/gen_error_pages.py", file=sys.stderr)
        return 1 if drift or orphans else 0

    for path, text in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
