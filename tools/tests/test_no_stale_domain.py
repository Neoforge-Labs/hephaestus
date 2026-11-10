"""The public host is hephkit.dev; the pre-move host must not survive anywhere."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python" / "hephkit" / "src"))

from hephkit.errors import TYPE_BASE_URL  # noqa: E402

# Assembled from parts so that this file does not itself contain the string it hunts.
STALE_HOST = "neoforgelabs" + ".tech"

# Documents whose subject is the move itself. They name the old host on purpose,
# to record what was weighed; scrubbing them would delete that record. This is an
# explicit allow-list, not a wildcard: a stale host anywhere else must still fail.
MOVE_DOCUMENTS = frozenset(
    {
        "docs/adr/0019-the-public-domain-is-hephkit-dev.md",
        "docs/superpowers/specs/2026-11-10-hephkit-dev-domain-design.md",
    }
)


def _tracked_and_new_files() -> list[str]:
    # Tracked files plus untracked-but-not-ignored ones, so the guard also covers
    # a file that has not been committed yet.
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def test_old_host_appears_in_no_tracked_file() -> None:
    offenders: list[str] = []
    for rel in _tracked_and_new_files():
        if rel in MOVE_DOCUMENTS:
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        # Search raw bytes, so a file that is not valid UTF-8 cannot hide the host.
        if STALE_HOST.encode() in path.read_bytes():
            offenders.append(rel)
    assert offenders == []


def test_type_base_url_is_hephkit_dev_and_keeps_its_trailing_slash() -> None:
    assert TYPE_BASE_URL == "https://hephkit.dev/errors/"
    assert TYPE_BASE_URL.endswith("/")


def test_composed_type_matches_the_spec_example() -> None:
    assert TYPE_BASE_URL + "HEPH-VAL-422" == "https://hephkit.dev/errors/HEPH-VAL-422"
