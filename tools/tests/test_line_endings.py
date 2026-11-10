"""The committed line endings cannot drift, because hashes are pinned over raw bytes.

``tools/brand-provenance.txt`` records the sha256 of each brand source and of each
generated PNG, and ``tools/gen_brand_raster.py --check`` compares those hashes. A
checkout that rewrote line endings -- git on Windows with ``core.autocrlf=true``
does exactly that -- would change the bytes of every text source and fail the
check for a contributor who changed nothing. ``.gitattributes`` pins the working
tree to LF so the hashes mean the same thing on every platform.

These tests assert the invariant rather than the file's wording: they ask git what
it would actually do to each pinned file, so a reworded ``.gitattributes`` that
still pins LF passes and a well-worded one that misses a file does not.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GITATTRIBUTES = REPO_ROOT / ".gitattributes"
PROVENANCE = REPO_ROOT / "tools" / "brand-provenance.txt"
BRAND = Path("docs/site/public/brand")


def _check_attr(attr: str, paths: list[str]) -> dict[str, str]:
    """Ask git what `attr` resolves to for each path. Keys are the paths given."""
    out = subprocess.run(
        ["git", "check-attr", "--stdin", attr],
        cwd=REPO_ROOT,
        input="\n".join(paths),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    resolved = {}
    for line in out.splitlines():
        # "<path>: <attr>: <value>", and a path cannot contain ": " here.
        path, _, value = line.rsplit(": ", 2)
        resolved[path] = value
    return resolved


def _provenance_entries(kind: str) -> list[str]:
    lines = PROVENANCE.read_text(encoding="utf-8").splitlines()
    return [
        parts[2]
        for line in lines
        if not line.startswith("#") and (parts := line.split()) and parts[0] == kind
    ]


def test_gitattributes_exists() -> None:
    assert GITATTRIBUTES.is_file(), (
        ".gitattributes is missing: without it a Windows checkout rewrites line "
        "endings and tools/gen_brand_raster.py --check fails on unchanged sources"
    )


def test_every_hashed_text_source_is_pinned_to_lf() -> None:
    sources = _provenance_entries("source")
    assert sources, "no source lines in tools/brand-provenance.txt"
    paths = [str(BRAND / name) for name in sources]
    eol = _check_attr("eol", paths)
    for path in paths:
        assert eol[path] == "lf", (
            f"{path} is hashed in tools/brand-provenance.txt but its eol attribute "
            f"is {eol[path]!r}, so a checkout could rewrite its bytes and break --check"
        )


def test_every_hashed_png_is_marked_binary() -> None:
    outputs = _provenance_entries("output")
    assert outputs, "no output lines in tools/brand-provenance.txt"
    paths = [str(BRAND / name) for name in outputs]
    text = _check_attr("text", paths)
    for path in paths:
        assert text[path] == "unset", (
            f"{path} is a hashed PNG but its text attribute is {text[path]!r}; it must "
            "be unset (marked binary) so git never touches its bytes"
        )


def test_no_tracked_file_currently_holds_a_carriage_return() -> None:
    """The pin is only worth having if the tree it pins is already clean."""
    found = subprocess.run(
        ["git", "grep", "-I", "--files-with-matches", "\r"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # git grep exits 1 when there are no matches, which is the passing case.
    assert found.returncode == 1, f"tracked files contain CR:\n{found.stdout}"
