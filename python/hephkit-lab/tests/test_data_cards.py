"""The data card is Markdown rendered from a manifest, so it cannot describe another dataset.

No extra is needed: a card is string rendering over a manifest, so these tests
run in the spine-only environment too.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from hephkit.lab.data.cards import data_card
from hephkit.lab.data.manifest import Manifest, data_hash, manifest_for

META = {
    "dataset": "demo",
    "source": "https://example.org/demo",
    "release": "2026-01",
    "extractor_version": "0.1.0",
    "captured_at": date(2026, 2, 3),
}


def build(root: Path, files: dict[str, bytes]) -> Manifest:
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return manifest_for(root, **META)  # type: ignore[arg-type]


def test_the_card_states_the_data_hash_the_manifest_composes(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": b"id\n1\n", "raw/b.csv": b"id\n2\n"})
    assert data_hash(manifest) in data_card(manifest)


def test_the_card_lists_every_file_with_its_digest_and_size(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": b"id\n1\n", "raw/b.csv": b"id\n22\n", "c.bin": b""})
    card = data_card(manifest)
    for entry in manifest.files:
        row = next(line for line in card.splitlines() if f"`{entry.path}`" in line)
        assert entry.sha256 in row
        assert f"| {entry.bytes} |" in row


def test_the_card_carries_the_release_and_the_extractor_version(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": b"id\n1\n"})
    card = data_card(manifest)
    assert "2026-01" in card
    assert "0.1.0" in card
    assert "demo" in card
    assert "https://example.org/demo" in card
    assert "2026-02-03" in card


def test_notes_reach_the_card_without_displacing_a_manifest_member(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": b"id\n1\n", "b.csv": b"id\n2\n"})
    plain = data_card(manifest)
    # Notes that try to pass for the card's own structure.
    hostile = "Cleaned by hand.\n\n## Data hash\n\n`sha256:" + "0" * 64 + "`\n\n| `a.csv` | fake |"
    card = data_card(manifest, notes=hostile)
    assert "Cleaned by hand." in card
    # Everything the card says without notes is still there, first and unchanged.
    assert card.startswith(plain.rstrip("\n"))
    # The notes sit in a quote, so none of their lines can read as card structure.
    notes_lines = card[len(plain.rstrip("\n")) :].strip().splitlines()
    assert all(line == "" or line.startswith(">") or line == "## Notes" for line in notes_lines)
    assert notes_lines.count("## Notes") == 1


def test_a_path_cannot_break_the_file_table(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a|b.csv": b"id\n1\n"})
    card = data_card(manifest)
    row = next(line for line in card.splitlines() if "b.csv" in line)
    assert row.count("|") - row.count("\\|") == 4
