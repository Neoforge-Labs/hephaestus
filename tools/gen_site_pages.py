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
* ``spec/heph-spec.md``           -> ``spec/index.md`` (behind a generated note that
  separates the spec version from the package version)
* ``docs/adr/NNNN-*.md``          -> ``adrs/NNNN-*.md``, ``adrs/index.md`` (the ``/adrs``
  list, one link per ADR) and ``adrs/_meta.ts``
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
ERRORS_SRC = Path("spec/errors.yaml")
SPEC_SRC = Path("spec/heph-spec.md")
DESIGN_SRC = Path("docs/superpowers/specs/2026-11-04-hephaestus-design.md")

# Product and research project names that must not appear on the roadmap page.
# Synced ADR text is exempt: it is copied verbatim.
MATURITIES = ("experimental", "beta", "stable")

PRIVATE_NAMES = ("Collie", "Domus", "SAWA", "NeoRx")

# Rollout step titles that carry a private name, rewritten to name the capability.
# The generator fails if the design's wording changes, so a stale override cannot hide.
_CAPABILITY_TITLES = {"Weeks 3–4: Collie core (product)": "Weeks 3–4: Product core"}

GENERATED_MARKER = "GENERATED FILE - do not edit by hand"

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
    for m in mods:
        if m.get("status") == "shipped" and m.get("maturity") not in MATURITIES:
            raise ValueError(
                f"{MODULES_SRC}: module {m.get('name', '<unnamed>')!r} has maturity {m.get('maturity')!r}; "
                f"shipped modules need one of {', '.join(MATURITIES)}"
            )
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

This list is not exhaustive: it names the headline modules from the design's rollout.
See the [roadmap](/roadmap) for the full picture.

| Module | Home | Phase | Spec |
| --- | --- | --- | --- |
{planned_rows}
"""
    )


def current_phase(mods: list[dict[str, Any]]) -> int:
    """The phase being built now, derived rather than declared.

    Everything `shipped` is the work of a completed-or-current phase, and every
    `planned` row carries the phase that will bring it. So the phase in progress
    is one below the earliest planned phase. When phase 2's modules ship and
    their rows move to `shipped`, this follows on its own -- there is no "current
    phase" constant anywhere to go stale.
    """
    planned = [int(m["phase"]) for m in mods if m.get("status") == "planned" and m.get("phase")]
    if not planned:
        raise ValueError(f"{MODULES_SRC}: no planned rows, so the current phase cannot be derived")
    return min(planned) - 1


def render_site_data(mods: list[dict[str, Any]], design: str, spec: str, errors: list[dict[str, Any]]) -> str:
    """Build-time data for the landing page, as JSON.

    The landing page states what runs today, what is coming and which phase we
    are in. Every one of those is a claim, so none of them is typed into a
    component: this file is the single generated source they all read, and
    `--check` fails if it drifts from the registries.
    """
    shipped = [m for m in mods if m.get("status") == "shipped"]
    planned = [m for m in mods if m.get("status") == "planned"]
    phases = []
    for i, title in enumerate(parse_rollout(design), start=1):
        title = _CAPABILITY_TITLES.get(title, title)
        for name in PRIVATE_NAMES:
            if name in title:
                raise ValueError(f"rollout phase {i} names {name}; add a capability title for it")
        # "Weeks 3-4: Product core" -> the part after the week estimate.
        phases.append({"phase": i, "title": title.split(": ", 1)[-1].strip()})
    data = {
        "_generated": "GENERATED FILE - do not edit by hand. Source: spec/modules.yaml, spec/errors.yaml, "
        "spec/heph-spec.md and the design's Rollout. Regenerate with `uv run tools/gen_site_pages.py`.",
        "specVersion": parse_spec_version(spec),
        "currentPhase": current_phase(mods),
        "errorCodeCount": len(errors),
        "shipped": [
            {"name": m["name"], "home": m["home"], "maturity": m["maturity"]}
            for m in sorted(shipped, key=lambda m: (m["home"], m["name"]))
        ],
        "planned": [
            {"name": m["name"], "home": m["home"], "phase": int(m["phase"])}
            for m in sorted(planned, key=lambda m: (int(m["phase"]), m["name"]))
        ],
        "phases": phases,
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def parse_rollout(design: str) -> list[str]:
    """The titles of the seven rollout phases, in order.

    The Rollout section holds eight bold numbered items: seven phases and a final
    "On demand" backlog, which is deliberately not a phase. Anything else is an
    error, so a new or renumbered item cannot be dropped unnoticed.
    """
    if "\n## Rollout\n" not in design:
        raise ValueError(f"{DESIGN_SRC}: no Rollout section")
    section = design.split("\n## Rollout\n", 1)[1].split("\n## ", 1)[0]
    items = re.findall(r"^(\d+)\. \*\*(.+?)[.:]\*\*", section, re.M)
    if [int(n) for n, _ in items] != list(range(1, 9)):
        raise ValueError(
            f"{DESIGN_SRC}: Rollout must hold exactly eight numbered items (seven phases, then the "
            f"on-demand backlog); found {len(items)}: {[int(n) for n, _ in items]}"
        )
    if not items[7][1].startswith("On demand"):
        raise ValueError(f"{DESIGN_SRC}: Rollout item 8 must begin 'On demand', not {items[7][1]!r}")
    return [t for _, t in items[:7]]


def render_roadmap(design: str) -> str:
    items = []
    titles = parse_rollout(design)
    for i, title in enumerate(titles, start=1):
        title = _CAPABILITY_TITLES.get(title, title)
        for name in PRIVATE_NAMES:
            if name in title:
                raise ValueError(f"roadmap step {i} names {name}; add a capability title for it")
        items.append(f"{i}. {_escape(title)}")
    stale = [t for t in _CAPABILITY_TITLES if t not in titles]
    if stale:
        raise ValueError(f"the design's rollout no longer has the step(s) {stale}; update _CAPABILITY_TITLES")
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


_SPEC_VERSION = re.compile(r"^- \*\*Version:\*\* (\S+)\s*$", re.M)


def parse_spec_version(spec: str) -> str:
    m = _SPEC_VERSION.search(spec)
    if not m:
        raise ValueError(f"{SPEC_SRC}: no '- **Version:** X.Y.Z' line; the spec page cannot state its version")
    return m.group(1)


def render_spec_note(spec_version: str) -> str:
    """A visible note above the synced spec. It carries the spec version, read from the
    spec, and deliberately no package version: that is stated by the project's releases."""
    return (
        f"> **Two version numbers.** This page is version {spec_version} of the specification. "
        "The packages (`hephkit`, `hephkit-core` and the Go module) are versioned independently: "
        "a change to the specification bumps the spec version, while package releases follow their own "
        "commit history, so the two numbers need not match. "
        "Package versions are published with the project's releases.\n\n"
    )


def _synced(source: str, title: str, body: str) -> str:
    return _front_matter(source, title) + body


def _title(text: str, fallback: str) -> str:
    m = re.match(r"# (.+)", text)
    return m.group(1).strip() if m else fallback


def adr_sources(repo_root: Path) -> list[Path]:
    return sorted(
        p for p in (repo_root / ADR_SRC).glob("[0-9][0-9][0-9][0-9]-*.md") if not p.name.startswith("0000-")
    )


def render_adr_index(rows: list[tuple[str, str]]) -> str:
    """The ``/adrs`` landing page: every ADR by number and title, linked to its page."""
    items = "\n".join(f"- [{_escape(title)}](/adrs/{slug})" for slug, title in rows)
    return (
        _front_matter("docs/adr/*.md", "Decisions")
        + f"""\
# Decisions

Architecture decision records. Each is numbered and never edited after
acceptance; a changed decision is superseded by a new record.

{items}
"""
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
    out[content / "_snippets/site-data.json"] = render_site_data(
        mods,
        (repo_root / DESIGN_SRC).read_text(encoding="utf-8"),
        spec,
        yaml.safe_load((repo_root / ERRORS_SRC).read_text(encoding="utf-8")),
    )
    note = render_spec_note(parse_spec_version(spec))
    out[content / "spec/index.md"] = _synced("spec/heph-spec.md", _title(spec, "heph-spec"), note + spec)

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
    out[content / "adrs/index.md"] = render_adr_index(rows)
    out[content / "adrs/_meta.ts"] = _meta(
        "docs/adr/*.md", "Sidebar order of the ADRs: numeric.", [("index", "Decisions"), *rows]
    )
    return out


def _is_generated(path: Path) -> bool:
    """True if the file carries the generated marker (it is ours to delete)."""
    try:
        return GENERATED_MARKER in path.read_text(encoding="utf-8")[:400]
    except (OSError, UnicodeDecodeError):
        return False


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
            reason = "is stale or missing"
            if path in orphans:
                reason = "has no source" if _is_generated(path) else "is hand-written, not generated, and has no source"
            print(f"{path.relative_to(root / CONTENT)} {reason}; run: uv run tools/gen_site_pages.py", file=sys.stderr)
        return 1 if drift or orphans else 0

    for path in orphans:
        if _is_generated(path):
            path.unlink()
        else:  # never delete what a human wrote
            print(
                f"{path.relative_to(root / CONTENT)} is not generated and has no source; left in place",
                file=sys.stderr,
            )
    for path, text in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
