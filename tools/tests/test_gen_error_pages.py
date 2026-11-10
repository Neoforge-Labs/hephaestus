"""Tests for tools/gen_error_pages.py."""

import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen_error_pages import INDEX_RELPATH, META_RELPATH, PAGES_RELDIR, generate, main  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ERRORS = REPO_ROOT / "spec" / "errors.yaml"


def _entries() -> list[dict[str, object]]:
    return yaml.safe_load(ERRORS.read_text(encoding="utf-8"))


def _root(tmp_path: Path) -> Path:
    (tmp_path / "spec").mkdir()
    shutil.copy(ERRORS, tmp_path / "spec" / "errors.yaml")
    return tmp_path


def test_one_page_per_code() -> None:
    pages = generate(REPO_ROOT)
    codes = [e["code"] for e in _entries()]
    assert len(codes) == 12
    page_paths = {p for p in pages if p.suffix == ".mdx" and p != REPO_ROOT / INDEX_RELPATH}
    assert page_paths == {REPO_ROOT / PAGES_RELDIR / f"{code}.mdx" for code in codes}
    assert set(pages) - page_paths == {REPO_ROOT / INDEX_RELPATH, REPO_ROOT / META_RELPATH}
    assert PAGES_RELDIR == Path("docs/site/content/errors")  # URL is /errors/<code> (spec 1.4)


def test_page_contains_registry_fields() -> None:
    entry = next(e for e in _entries() if e["code"] == "HEPH-IDEMP-409")
    text = generate(REPO_ROOT)[REPO_ROOT / PAGES_RELDIR / "HEPH-IDEMP-409.mdx"]
    assert str(entry["title"]) in text
    assert "409" in text
    assert str(entry["detail_hint"]) in text
    assert str(entry["guidance"]) in text
    # the caller-facing and developer-facing prose are presented as distinct things
    assert text.index(str(entry["detail_hint"])) < text.index(str(entry["guidance"]))
    assert "non-normative" in text.lower()


def test_pages_carry_generated_header() -> None:
    for path, text in generate(REPO_ROOT).items():
        if path.suffix != ".mdx":
            continue
        head = text.split("\n---\n", 1)[0]
        assert "spec/errors.yaml" in head, path
        assert "do not edit" in head.lower(), path
        assert text.startswith("---\n# GENERATED"), path  # front matter must stay first for Nextra


def test_prose_is_mdx_safe() -> None:
    # No raw MDX-significant character may reach the compiler outside an escape or code span.
    for path, text in generate(REPO_ROOT).items():
        if path.suffix != ".mdx":
            continue
        body = text.split("\n---\n", 1)[1]
        body = re.sub(r"`[^`\n]*`", "", body)  # code spans are literal
        body = re.sub(r"\\.", "", body)  # backslash escapes are literal
        assert not re.search(r"[{}<>]", body), path


def test_hostile_prose_is_neutralised(tmp_path: Path) -> None:
    root = _root(tmp_path)
    reg = root / "spec" / "errors.yaml"
    text = reg.read_text(encoding="utf-8").replace("Retry after it completes.", "Retry {1+1} <b>x</b> a*b_c [x](y).", 1)
    reg.write_text(text, encoding="utf-8")
    page = generate(root)[root / PAGES_RELDIR / "HEPH-IDEMP-409.mdx"]
    assert "{1+1}" not in page and "<b>" not in page


def test_check_detects_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    assert main(["--check"], root=root) == 0
    victim = root / PAGES_RELDIR / "HEPH-IDEMP-409.mdx"
    victim.write_text(victim.read_text(encoding="utf-8") + "hand edit\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["--check"], root=root) == 1
    assert "HEPH-IDEMP-409.mdx" in capsys.readouterr().err
    assert victim.read_text(encoding="utf-8").endswith("hand edit\n")  # --check never writes


def test_check_detects_meta_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    meta = root / META_RELPATH
    meta.write_text(meta.read_text(encoding="utf-8") + "// hand edit\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["--check"], root=root) == 1
    assert "_meta.ts" in capsys.readouterr().err


def test_check_detects_missing_and_orphan_pages(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    (root / PAGES_RELDIR / "HEPH-NF-404.mdx").unlink()
    capsys.readouterr()
    assert main(["--check"], root=root) == 1
    assert "HEPH-NF-404.mdx" in capsys.readouterr().err
    assert main([], root=root) == 0
    orphan = root / PAGES_RELDIR / "HEPH-OLD-404.mdx"
    orphan.write_text("stale\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["--check"], root=root) == 1
    assert "HEPH-OLD-404.mdx" in capsys.readouterr().err


def test_output_is_deterministic() -> None:
    first = generate(REPO_ROOT)
    second = generate(REPO_ROOT)
    assert first == second
    assert all(t.encode() == second[p].encode() for p, t in first.items())


def test_invalid_registry_is_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "spec" / "errors.yaml").write_text("- code: nope\n  status: 200\n", encoding="utf-8")
    assert main([], root=root) == 1
    assert not (root / PAGES_RELDIR).exists()


def test_every_registry_code_has_a_committed_page() -> None:
    codes = {str(e["code"]) for e in _entries()}
    committed = {p.stem for p in (REPO_ROOT / PAGES_RELDIR).glob("*.mdx") if p.name != "index.mdx"}
    assert codes - committed == set(), "registry code with no committed page"
    assert committed - codes == set(), "committed page with no registry code"


def test_meta_is_generated_with_header_in_registry_order() -> None:
    meta = generate(REPO_ROOT)[REPO_ROOT / META_RELPATH]
    assert "GENERATED FILE - do not edit by hand" in meta and "spec/errors.yaml" in meta
    keys = re.findall(r'^\s*"(HEPH-[A-Z]+-\d+)"\s*:', meta, re.MULTILINE)
    assert keys == [str(e["code"]) for e in _entries()]


def test_committed_pages_are_fresh() -> None:
    assert main(["--check"], root=REPO_ROOT) == 0


def test_index_links_equal_registry_codes() -> None:
    pages = generate(REPO_ROOT)
    text = pages[REPO_ROOT / INDEX_RELPATH]
    targets = re.findall(r"\]\(/errors/([^)]+)\)", text)
    codes = [str(e["code"]) for e in _entries()]
    assert targets == codes  # both directions, registry order, no dead links
    assert text.startswith("---\n# GENERATED") and "spec/errors.yaml" in text
    committed = (REPO_ROOT / INDEX_RELPATH).read_text(encoding="utf-8")
    assert committed == text


def test_nothing_links_to_the_old_reference_index() -> None:
    assert not (REPO_ROOT / "docs/site/content/reference/errors.mdx").exists()
    for path in (REPO_ROOT / "docs/site/content").rglob("*.mdx"):
        assert "/reference/errors" not in path.read_text(encoding="utf-8"), path


@pytest.mark.parametrize("name", ["notes.mdx", "index.mdx.bak", "heph-old-404.mdx"])
def test_check_reports_any_stray_file_in_the_errors_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    root = _root(tmp_path)
    assert main([], root=root) == 0
    assert main(["--check"], root=root) == 0
    (root / PAGES_RELDIR / name).write_text("stray\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["--check"], root=root) == 1
    assert name in capsys.readouterr().err
