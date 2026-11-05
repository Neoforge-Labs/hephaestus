# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Generate the derived docs pages that are not error codes.

Run with ``uv run tools/gen_site_pages.py`` to write the pages, or with
``--check`` to exit 1 (naming each file) if a committed page is missing, stale
or has no source. PyYAML is declared inline (PEP 723).

Sources and outputs, all under ``docs/site/content/``:

* ``conventions/attributes.yaml`` -> ``reference/conventions.mdx``
* ``spec/modules.yaml``           -> ``reference/modules.mdx``
* ``spec/heph-spec.md``           -> ``spec/index.md``
* ``docs/adr/NNNN-*.md``          -> ``adrs/NNNN-*.md`` and ``adrs/_meta.ts``
* the design's Rollout section    -> ``roadmap.mdx``

``reference/_meta.ts`` orders the two reference pages.

The spec and the ADRs are synced as ``.md``, not ``.mdx``: Nextra processes
``.md`` as plain markdown, where ``{`` and ``<`` in the existing prose are not
JSX or expressions, so the bodies stay byte-identical to their sources. The one
transformation is ``rewrite_adr_links``: markdown links to another ADR by file
name become site paths. Pages composed here (conventions, modules, roadmap) are
``.mdx`` and escape their text as ``gen_error_pages.py`` does.

The output is a pure function of the sources: fixed order, no timestamps.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

CONTENT = Path("docs/site/content")
ADR_SRC = Path("docs/adr")
ATTRIBUTES_SRC = Path("conventions/attributes.yaml")
MODULES_SRC = Path("spec/modules.yaml")
SPEC_SRC = Path("spec/heph-spec.md")
DESIGN_SRC = Path("docs/superpowers/specs/2026-11-04-hephaestus-design.md")

# Product and research project names that must not appear on the roadmap page.
# Synced ADR text is exempt: it is copied verbatim.
PRIVATE_NAMES = ("Collie", "Domus", "SAWA", "NeoRx")

# Rollout step titles that carry a private name, rewritten to name the capability.
# The generator fails if the design's wording changes, so a stale override cannot hide.
_CAPABILITY_TITLES = {"Weeks 3–4: Collie core (product)": "Weeks 3–4: Product core"}

_SPECIAL = re.compile(r"([\\`*_{}\[\]<>|#&~^$!])")
_ADR_LINK = re.compile(
    r"\]\((?:\./|\.\./adr/|/?docs/adr/)?(\d{4}-[a-z0-9-]+)\.md(#[^)\s]*)?\)"
)


def _escape(text: str) -> str:
    """Make prose literal in MDX; renders identically to the source."""
    return _SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _front_matter(source: str, title: str, regenerate: str = "uv run tools/gen_site_pages.py") -> str:
    """Front matter with the generated notice inside it (Nextra needs it at byte 0)."""
    return (
        "---\n"
        f"# GENERATED FILE - do not edit by hand. Source: {source}.\n"
        f"# Regenerate with `{regenerate}`; CI runs --check.\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        "---\n\n"
    )


def _meta(source: str, comment: str, rows: list[tuple[str, str]]) -> str:
    body = ",\n".join(f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}" for k, v in rows)
    return f"""\
import type {{ MetaRecord }} from 'nextra'

// GENERATED FILE - do not edit by hand. Source: {source}.
// Regenerate with `uv run tools/gen_site_pages.py`; CI runs --check.
// {comment}
const meta: MetaRecord = {{
{body}
}}

export default meta
"""


def render_conventions(attrs: list[dict[str, Any]]) -> str:
    rows = "\n".join(
        f"| `{a['name']}` | {a['type']} | {_escape(str(a['description']))} | {'**PII**' if a.get('pii') else 'no'} |"
        for a in attrs
    )
    return (
        _front_matter("conventions/attributes.yaml", "Telemetry conventions")
        + f"""\
# Telemetry conventions

Attribute names shared by every language. Constants for Python, TypeScript, Go
and Rust are generated from `conventions/attributes.yaml`. Attributes marked
PII are redacted from logs by default.

| Attribute | Type | Meaning | PII |
| --- | --- | --- | --- |
{rows}
"""
    )


def render_modules(mods: list[dict[str, Any]]) -> str:
    shipped = [m for m in mods if m["status"] == "shipped"]
    planned = [m for m in mods if m["status"] == "planned"]

    def spec(m: dict[str, Any]) -> str:
        return f"section {m['spec_section']}" if m.get("spec_section") else "-"

    shipped_rows = "\n".join(
        f"| `{m['name']}` | `{m['home']}` | `{m['maturity']}` | {spec(m)} |" for m in shipped
    )
    planned_rows = "\n".join(f"| `{m['name']}` | `{m['home']}` | {m['phase']} | {spec(m)} |" for m in planned)
    return (
        _front_matter("spec/modules.yaml", "Modules")
        + f"""\
# Modules

What runs today and what does not yet. Maturity is `experimental`, `beta` or
`stable`; new work starts `experimental`.

## Shipped

| Module | Home | Maturity | Spec |
| --- | --- | --- | --- |
{shipped_rows}

## Planned

| Module | Home | Phase | Spec |
| --- | --- | --- | --- |
{planned_rows}
"""
    )


def parse_rollout(design: str) -> list[str]:
    """The titles of the seven numbered rollout phases, in order."""
    if "\n## Rollout\n" not in design:
        raise ValueError(f"{DESIGN_SRC}: no Rollout section")
    section = design.split("\n## Rollout\n", 1)[1].split("\n## ", 1)[0]
    titles = re.findall(r"^(\d+)\. \*\*(.+?)\.\*\*", section, re.M)
    phases = [t for n, t in titles if n.isdigit()][:7]
    if [int(n) for n, _ in titles[:7]] != list(range(1, 8)) or len(phases) != 7:
        raise ValueError(f"{DESIGN_SRC}: Rollout does not hold seven numbered steps")
    return phases


def render_roadmap(design: str) -> str:
    items = []
    for i, title in enumerate(parse_rollout(design), start=1):
        title = _CAPABILITY_TITLES.get(title, title)
        for name in PRIVATE_NAMES:
            if name in title:
                raise ValueError(f"roadmap step {i} names {name}; add a capability title for it")
        items.append(f"{i}. {_escape(title)}")
    return (
        _front_matter("the Rollout section of the design", "Roadmap")
        + """\
# Roadmap

Hephaestus is built in seven phases that share one core. Each phase ends at a
gate that a real project has to pass. Week counts are estimates.

"""
        + "\n".join(items)
        + """

What runs today is on the [modules page](/reference/modules). Further work
enters as `experimental` when a project asks for it.
"""
    )


def rewrite_adr_links(text: str, known: set[str] | None = None) -> str:
    """Point markdown links to another ADR file at its site path.

    ``known`` limits the rewrite to ADRs that have a page (the template does not).
    """

    def sub(m: re.Match[str]) -> str:
        if known is not None and m.group(1) not in known:
            return m.group(0)
        return f"](/adrs/{m.group(1)}{m.group(2) or ''})"

    return _ADR_LINK.sub(sub, text)


def _synced(source: str, title: str, body: str) -> str:
    return _front_matter(source, title) + body


def _title(text: str, fallback: str) -> str:
    m = re.match(r"# (.+)", text)
    return m.group(1).strip() if m else fallback


def adr_sources(repo_root: Path) -> list[Path]:
    return sorted(
        p for p in (repo_root / ADR_SRC).glob("[0-9][0-9][0-9][0-9]-*.md") if not p.name.startswith("0000-")
    )


def generate(repo_root: Path) -> dict[Path, str]:
    """Map each output path to its content."""
    content = repo_root / CONTENT
    attrs = yaml.safe_load((repo_root / ATTRIBUTES_SRC).read_text(encoding="utf-8"))
    mods = yaml.safe_load((repo_root / MODULES_SRC).read_text(encoding="utf-8"))
    out: dict[Path, str] = {
        content / "reference/conventions.mdx": render_conventions(attrs),
        content / "reference/modules.mdx": render_modules(mods),
        content / "reference/_meta.ts": _meta(
            "the pages in this directory",
            "Sidebar order of the reference pages.",
            [("conventions", "Telemetry conventions"), ("modules", "Modules")],
        ),
        content / "roadmap.mdx": render_roadmap((repo_root / DESIGN_SRC).read_text(encoding="utf-8")),
    }

    spec = (repo_root / SPEC_SRC).read_text(encoding="utf-8")
    out[content / "spec/index.md"] = _synced("spec/heph-spec.md", _title(spec, "heph-spec"), spec)

    sources = adr_sources(repo_root)
    known = {p.stem for p in sources}
    rows = []
    for src in sources:
        text = src.read_text(encoding="utf-8")
        title = _title(text, src.stem)
        out[content / "adrs" / src.name] = _synced(
            f"docs/adr/{src.name}", title, rewrite_adr_links(text, known)
        )
        rows.append((src.stem, title))
    out[content / "adrs/_meta.ts"] = _meta("docs/adr/*.md", "Sidebar order of the ADRs: numeric.", rows)
    return out


def _orphans(root: Path, pages: dict[Path, str]) -> list[Path]:
    """Files in generated-only directories that no source produces."""
    found: list[Path] = []
    for rel in ("adrs", "reference", "spec"):
        directory = root / CONTENT / rel
        if directory.is_dir():
            found += [p for p in sorted(directory.iterdir()) if p.is_file() and p not in pages]
    return found


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    check = "--check" in args
    unknown = [a for a in args if a != "--check"]
    if unknown:
        print(f"usage: gen_site_pages.py [--check] (unknown: {' '.join(unknown)})", file=sys.stderr)
        return 2
    root = root or Path(__file__).resolve().parents[1]

    try:
        pages = generate(root)
    except (ValueError, OSError) as err:
        print(err, file=sys.stderr)
        return 1

    orphans = _orphans(root, pages)
    if check:
        drift = [p for p, text in pages.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
        for path in drift + orphans:
            reason = "has no source" if path in orphans else "is stale or missing"
            print(f"{path.relative_to(root / CONTENT)} {reason}; run: uv run tools/gen_site_pages.py", file=sys.stderr)
        return 1 if drift or orphans else 0

    for path in orphans:
        path.unlink()
    for path, text in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
