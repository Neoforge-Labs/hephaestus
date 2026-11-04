"""Tests for tools/check_adrs.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_adrs import check_adrs  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

BODY = "# {n}. Title\n\n## Status\nAccepted\n\n## Context\nc\n\n## Decision\nd\n\n## Consequences\nq\n"


def _write(adr_dir: Path, name: str, body: str | None = None) -> None:
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / name).write_text(body if body is not None else BODY.format(n=name[:4]))


def test_adr_files_are_numbered_and_complete() -> None:
    adrs = [p for p in (REPO_ROOT / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md") if not p.name.startswith("0000-")]
    assert len(adrs) >= 15
    assert check_adrs(REPO_ROOT) == []


def test_rejects_gap(tmp_path: Path) -> None:
    adr = tmp_path / "docs" / "adr"
    _write(adr, "0001-first.md")
    _write(adr, "0003-third.md")
    errors = check_adrs(tmp_path)
    assert any("0002" in e for e in errors)


def test_template_is_excluded(tmp_path: Path) -> None:
    adr = tmp_path / "docs" / "adr"
    _write(adr, "0000-template.md", "# template with no required headings\n")
    _write(adr, "0001-first.md")
    assert check_adrs(tmp_path) == []


def test_rejects_missing_heading(tmp_path: Path) -> None:
    adr = tmp_path / "docs" / "adr"
    _write(adr, "0001-first.md", "# 1\n\n## Status\nAccepted\n\n## Context\nc\n")
    errors = check_adrs(tmp_path)
    assert any("## Decision" in e for e in errors)
    assert any("## Consequences" in e for e in errors)


def test_rejects_bad_prefix(tmp_path: Path) -> None:
    adr = tmp_path / "docs" / "adr"
    _write(adr, "0001-first.md")
    _write(adr, "12-short.md")
    errors = check_adrs(tmp_path)
    assert any("12-short.md" in e for e in errors)
