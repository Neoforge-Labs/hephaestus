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

# The docs site publishes every ADR verbatim (tools/gen_site_pages.py), so an
# allow-listed ADR has a generated twin under the site's content tree. It is the
# same deliberate record, carried by the same decision to keep it; redacting the
# copy would make the published ADR disagree with the one in the repo. Derived
# from MOVE_DOCUMENTS rather than listed, so the two can never drift apart.
GENERATED_ADR_PAGES = frozenset(
    f"docs/site/content/adrs/{Path(rel).name}" for rel in MOVE_DOCUMENTS if rel.startswith("docs/adr/")
)

EXEMPT = MOVE_DOCUMENTS | GENERATED_ADR_PAGES


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
        if rel in EXEMPT:
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


def test_each_exempt_adr_page_is_actually_generated() -> None:
    # If an allow-listed ADR has no published twin, the exemption covers a path
    # that does not exist, and a real stale reference could later claim it.
    for rel in sorted(GENERATED_ADR_PAGES):
        assert (REPO_ROOT / rel).is_file(), f"{rel} is exempt but not generated; run tools/gen_site_pages.py"
