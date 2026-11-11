# /// script
# requires-python = ">=3.12"
# ///
"""Fail if the exported site links to a page it does not contain.

Run with ``uv run tools/check_site_links.py`` after ``bun run --cwd docs/site
build``. It reads ``docs/site/out`` and reports every internal href with no file
behind it.

Why this and not a link crawler: the site is a static export, so "does this
resolve?" is a filesystem question with an exact answer, and the answer is
available in CI without a browser or the network. External links are NOT
checked -- a third party going down is not this repository's build breaking.

The resolution rules match the ``cleanUrls: true`` deployment in vercel.json:
``/errors/HEPH-MONEY-422`` is served by ``out/errors/HEPH-MONEY-422.html``, and
``/errors`` by ``out/errors.html`` or ``out/errors/index.html``. A link that
only works because the reader's browser follows a redirect is still a link that
resolves, so both spellings pass.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

OUT = Path("docs/site/out")

# href="..." and src="..." in the exported HTML.
_ATTR = re.compile(r"""\s(?:href|src)=["']([^"']+)["']""", re.I)

# Schemes and shapes that are not this site's own pages.
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.I)


def internal_targets(html: str) -> list[str]:
    """The site-internal paths an exported page links to."""
    found: list[str] = []
    for raw in _ATTR.findall(html):
        value = raw.strip()
        if not value or value.startswith("#") or _EXTERNAL.match(value):
            continue
        path = urlsplit(value).path
        if not path:
            continue
        found.append(unquote(path))
    return found


def _resolves(out: Path, target: str, page: Path) -> bool:
    if target.startswith("/"):
        candidate = out / target.lstrip("/")
    else:
        candidate = (page.parent / target).resolve()
        try:
            candidate.relative_to(out.resolve())
        except ValueError:
            # A relative link that climbs out of the export: never resolvable.
            return False
    # These are alternatives, not a branch: `/docs` is BOTH a directory holding
    # nested pages and a page of its own at `docs.html`, so testing is_dir()
    # first and stopping there reports every such link as broken. Any one of
    # the three spellings serving the URL means the link resolves.
    #
    # `.html` is appended rather than set with with_suffix(), which would eat
    # the extension of a name that legitimately contains a dot (`lab.repro`).
    return (
        candidate.is_file()
        or (candidate / "index.html").is_file()
        or candidate.with_name(candidate.name + ".html").is_file()
    )


def check_links(out: Path) -> list[str]:
    """Return one message per broken internal link, sorted."""
    if not out.is_dir():
        return [f"{out} does not exist; run the site build first"]
    pages = sorted(out.rglob("*.html"))
    if not pages:
        return [f"{out} holds no HTML; run the site build first"]

    broken: list[str] = []
    for page in pages:
        # Pagefind's own bundled UI is generated and not ours to police.
        if "_pagefind" in page.parts:
            continue
        html = page.read_text(encoding="utf-8", errors="replace")
        for target in internal_targets(html):
            if not _resolves(out, target, page):
                broken.append(f"{page.relative_to(out)} -> {target}")
    return sorted(set(broken))


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        print(f"usage: check_site_links.py (unexpected: {' '.join(args)})", file=sys.stderr)
        return 2
    root = root or Path(__file__).resolve().parents[1]
    broken = check_links(root / OUT)
    for message in broken:
        print(f"broken internal link: {message}", file=sys.stderr)
    if broken:
        print(f"{len(broken)} broken internal link(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
