"""The data card (design 8.2): the Markdown a reader gets for a dataset, rendered from its manifest.

A card is never typed by hand. It is a pure function of a
:class:`~hephkit.lab.data.manifest.Manifest`, so it cannot describe a dataset
other than the one the manifest names: it states the ``data_hash`` the manifest
composes, every member of the manifest, and one table row per file. The caller's
own words are appended last, under their own heading and quoted, so nothing a
note says can read as, or displace, a line the manifest produced.

Pure string rendering needs no extra, so this module runs in the spine.
"""

from __future__ import annotations

from hephkit.lab.data.manifest import Manifest, data_hash

__all__ = ["data_card"]


def _cell(text: str) -> str:
    """``text`` as one Markdown table cell: a ``|`` or a newline must not end or split the row."""
    return text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _inline(text: str) -> str:
    """``text`` as inline code that a backtick inside it cannot close early."""
    longest = run = 0
    for char in text:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def data_card(manifest: Manifest, *, notes: str | None = None) -> str:
    """Render ``manifest`` as a Markdown data card, with ``notes`` appended if given.

    The card carries the dataset name, source, release, extractor version and
    capture date; the ``data_hash`` (spec 10.2); and a table of every file with
    its SHA-256 and size. ``notes`` is the caller's own prose, placed in a final
    ``## Notes`` section with every line quoted, so a heading or table inside
    it stays text.
    """
    ordered = sorted(manifest.files, key=lambda f: f.path.encode())
    lines = [
        f"# Data card: {_cell(manifest.dataset)}",
        "",
        "## Provenance",
        "",
        f"- Dataset: {_inline(_cell(manifest.dataset))}",
        f"- Source: {_inline(_cell(manifest.source))}",
        f"- Release: {_inline(_cell(manifest.release))}",
        f"- Extractor version: {_inline(_cell(manifest.extractor_version))}",
        f"- Captured at: {manifest.captured_at.isoformat()}",
        "",
        "## Data hash",
        "",
        _inline(data_hash(manifest)),
        "",
        f"## Files ({len(ordered)})",
        "",
        "| Path | SHA-256 | Bytes |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {_inline(_cell(f.path))} | `{f.sha256}` | {f.bytes} |" for f in ordered
    )
    card = "\n".join(lines) + "\n"
    if notes is not None and notes.strip():
        quoted = "\n".join(f"> {line}".rstrip() for line in notes.strip().splitlines())
        card += "\n## Notes\n\n" + quoted + "\n"
    return card
