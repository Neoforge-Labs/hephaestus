"""Tests for tools/check_site_links.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_site_links import check_links, internal_targets  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _site(tmp_path: Path, pages: dict[str, str]) -> Path:
    out = tmp_path / "out"
    for rel, html in pages.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    return out


def test_a_missing_target_is_reported(tmp_path: Path) -> None:
    out = _site(tmp_path, {"index.html": '<a href="/nowhere">x</a>'})
    assert check_links(out) == ["index.html -> /nowhere"]


def test_clean_url_served_by_a_sibling_html_file(tmp_path: Path) -> None:
    out = _site(tmp_path, {"index.html": '<a href="/spec">x</a>', "spec.html": "<p>spec</p>"})
    assert check_links(out) == []


def test_clean_url_served_by_a_directory_index(tmp_path: Path) -> None:
    out = _site(tmp_path, {"index.html": '<a href="/guide">x</a>', "guide/index.html": "<p>g</p>"})
    assert check_links(out) == []


def test_a_path_that_is_both_a_directory_and_a_page(tmp_path: Path) -> None:
    """The case the first implementation got wrong.

    `/docs` is a page in its own right AND a directory of nested pages. Testing
    is_dir() first and stopping there reported every such link as broken -- 1529
    of them on the real site, which is the kind of false alarm that gets a gate
    switched off.
    """
    out = _site(
        tmp_path,
        {
            "index.html": '<a href="/docs">x</a>',
            "docs.html": "<p>docs</p>",
            "docs/errors.html": "<p>nested</p>",
        },
    )
    assert check_links(out) == []


def test_a_dotted_name_keeps_its_extension(tmp_path: Path) -> None:
    """`lab.repro` must look for `lab.repro.html`, not `lab.html`."""
    out = _site(tmp_path, {"index.html": '<a href="/lab.repro">x</a>', "lab.repro.html": "<p>r</p>"})
    assert check_links(out) == []


def test_external_and_anchor_links_are_not_checked(tmp_path: Path) -> None:
    out = _site(
        tmp_path,
        {
            "index.html": (
                '<a href="https://example.com/nope">a</a>'
                '<a href="//cdn.example.com/x.js">b</a>'
                '<a href="mailto:someone@example.com">c</a>'
                '<a href="#section">d</a>'
            )
        },
    )
    assert check_links(out) == []


def test_query_and_fragment_are_stripped_before_resolving(tmp_path: Path) -> None:
    out = _site(tmp_path, {"index.html": '<a href="/spec?x=1#top">x</a>', "spec.html": "<p>s</p>"})
    assert check_links(out) == []


def test_a_relative_link_escaping_the_export_is_reported(tmp_path: Path) -> None:
    out = _site(tmp_path, {"a/index.html": '<a href="../../../etc/passwd">x</a>'})
    assert check_links(out) == ["a/index.html -> ../../../etc/passwd"]


def test_pagefind_bundle_is_skipped(tmp_path: Path) -> None:
    out = _site(tmp_path, {"_pagefind/pagefind-ui.html": '<a href="/nowhere">x</a>'})
    assert check_links(out) == []


def test_missing_export_says_to_build_first(tmp_path: Path) -> None:
    assert "run the site build first" in check_links(tmp_path / "out")[0]


def test_empty_export_says_to_build_first(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    assert "run the site build first" in check_links(out)[0]


def test_src_attributes_are_checked_too(tmp_path: Path) -> None:
    out = _site(tmp_path, {"index.html": '<img src="/brand/missing.svg">'})
    assert check_links(out) == ["index.html -> /brand/missing.svg"]


def test_internal_targets_ignores_schemes_and_empty_values() -> None:
    html = '<a href="">a</a><a href="  ">b</a><a href="tel:+100">c</a><a href="/ok">d</a>'
    assert internal_targets(html) == ["/ok"]
