"""Dataset manifests and the digest scope (spec section 10).

A :class:`Manifest` describes one dataset as one extractor wrote it (10.1).
:func:`data_hash` collapses it to the hash a provenance record names (7.1) by
10.2's composition: the content hash of the canonical JSON of the
``{path, sha256, bytes}`` array sorted by ``path`` byte-wise. The hash is
computed by :func:`hephkit.hashing.content_hash`; each file's ``sha256`` is a
plain SHA-256 of its bytes and is an *input* to that hash, never a second
hashing scheme. File bytes are never concatenated, and the order of a directory
walk never reaches the hash.

Every refusal of an invalid manifest (10.4) is a :class:`ManifestError` carrying
``HEPH-LAB-412``: the registry routes "an artefact that exists but says the
wrong thing" there, and 422 is for experiment configs. A manifest file that is
absent altogether is ``HEPH-LAB-424``, as :class:`MissingManifestError`.

Which layer refuses what: the models refuse everything a document can be wrong
about on its own (an empty ``files``, a duplicate ``path``, a malformed
``sha256``, a negative or non-integer ``bytes``, an undefined or missing
member). Whether ``bytes`` agrees with a file is a fact about a directory, so
:func:`verify_manifest` refuses that, given the root the paths are relative to.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from hephkit.errors import LAB_412, LAB_424
from hephkit.hashing import content_hash

__all__ = [
    "FileDigest",
    "Manifest",
    "ManifestError",
    "MissingManifestError",
    "data_hash",
    "digest_file",
    "manifest_for",
    "parse_manifest",
    "read_manifest",
    "verify_manifest",
    "write_manifest",
]

#: Lowercase hex SHA-256, 64 characters (10.1).
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

_CHUNK = 1 << 20


class ManifestError(ValueError):
    """A manifest is invalid, or does not describe its files (``HEPH-LAB-412``)."""

    code = LAB_412


class MissingManifestError(ManifestError):
    """A manifest file is not there at all (``HEPH-LAB-424``)."""

    code = LAB_424


class FileDigest(BaseModel):
    """One file of a dataset: where it is, what its bytes hash to, how long it is (10.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    path: str
    sha256: Sha256Hex
    bytes: Annotated[int, Field(ge=0)]

    @field_validator("path")
    @classmethod
    def _path_is_relative_within_the_dataset(cls, path: str) -> str:
        """10.1: non-empty segments joined by ``/``, none ``.`` or ``..``, no leading ``/``."""
        if any(segment in ("", ".", "..") for segment in path.split("/")):
            raise ValueError(f"path {path!r} is not a relative path within the dataset")
        return path


class Manifest(BaseModel):
    """A dataset manifest (10.1). ``files`` keeps the order it was given; the hash does not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    source: str
    release: str
    extractor_version: str
    captured_at: date
    files: tuple[FileDigest, ...]

    @field_validator("files")
    @classmethod
    def _files_are_non_empty_and_unique(cls, files: tuple[FileDigest, ...]) -> tuple[FileDigest, ...]:
        if not files:
            raise ValueError("a manifest must list at least one file")
        seen: set[str] = set()
        for entry in files:
            if entry.path in seen:
                raise ValueError(f"duplicate path {entry.path!r}")
            seen.add(entry.path)
        return files

    def as_document(self) -> dict[str, Any]:
        """The manifest as a JSON-ready object, members in 10.1's order."""
        return {
            "dataset": self.dataset,
            "source": self.source,
            "release": self.release,
            "extractor_version": self.extractor_version,
            "captured_at": self.captured_at.isoformat(),
            "files": [
                {"path": f.path, "sha256": f.sha256, "bytes": f.bytes} for f in self.files
            ],
        }


def parse_manifest(document: Any) -> Manifest:
    """Build a :class:`Manifest` from a decoded JSON document, or refuse it (10.4)."""
    try:
        return Manifest.model_validate(document)
    except ValidationError as exc:
        raise ManifestError(f"invalid dataset manifest: {exc}") from exc


def digest_file(path: Path, *, relative_to: Path) -> FileDigest:
    """Digest one file; ``path`` in the result is POSIX-style and relative to ``relative_to``."""
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            sha.update(chunk)
            size += len(chunk)
    try:
        return FileDigest(
            path=path.relative_to(relative_to).as_posix(), sha256=sha.hexdigest(), bytes=size
        )
    except (ValueError, ValidationError) as exc:
        # `relative_to` raises a bare ValueError for a path outside the root, and
        # the model refuses a `..` segment that stays lexically inside it.
        raise ManifestError(f"{path} is not a file within {relative_to}: {exc}") from exc


def _walk(directory: Path) -> list[Path]:
    """Every file under ``directory``. Order is the filesystem's and means nothing."""
    found: list[Path] = []
    for entry in directory.iterdir():
        if entry.is_file():
            found.append(entry)
        elif entry.is_dir() and not entry.is_symlink():
            found.extend(_walk(entry))
    return found


def manifest_for(
    root: Path,
    *,
    dataset: str,
    source: str,
    release: str,
    extractor_version: str,
    captured_at: date,
) -> Manifest:
    """Describe every file under ``root``, sorted by path byte-wise (10.2)."""
    digests = sorted(
        (digest_file(p, relative_to=root) for p in _walk(root)),
        key=lambda d: d.path.encode(),
    )
    try:
        return Manifest(
            dataset=dataset,
            source=source,
            release=release,
            extractor_version=extractor_version,
            captured_at=captured_at,
            files=tuple(digests),
        )
    except ValidationError as exc:
        raise ManifestError(f"invalid dataset manifest for {root}: {exc}") from exc


def data_hash(manifest: Manifest) -> str:
    """The manifest's ``data_hash`` (10.2): the content hash of its sorted digest array."""
    ordered = sorted(manifest.files, key=lambda f: f.path.encode())
    return content_hash([f.model_dump() for f in ordered])


def verify_manifest(manifest: Manifest, root: Path) -> None:
    """Refuse a manifest whose ``bytes`` or ``sha256`` disagrees with the file it names (10.4).

    A file the manifest names that ``root`` does not hold is refused too: the
    manifest then describes a dataset that is not the one on disk.

    This verifies every entry the manifest names. It does NOT flag files present
    under ``root`` that the manifest omits: 10.4 does not require that stronger
    check, so a caller that needs "the manifest names everything there" must
    compare the listing itself (for instance against :func:`manifest_for`).
    """
    for entry in manifest.files:
        target = root / entry.path
        if not target.is_file():
            raise ManifestError(f"the manifest names {entry.path!r}, which {root} does not hold")
        actual = digest_file(target, relative_to=root)
        if actual.bytes != entry.bytes:
            raise ManifestError(
                f"{entry.path!r}: the manifest says {entry.bytes} bytes, the file is {actual.bytes}"
            )
        if actual.sha256 != entry.sha256:
            raise ManifestError(
                f"{entry.path!r}: the manifest says sha256 {entry.sha256}, the file hashes to {actual.sha256}"
            )


def write_manifest(manifest: Manifest, path: Path) -> Path:
    """Write the manifest as JSON at ``path`` and return ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest.as_document(), indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def read_manifest(path: Path) -> Manifest:
    """Read a manifest file, refusing one that is not a valid manifest."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MissingManifestError(f"no dataset manifest at {path}") from exc
    try:
        document = json.loads(text)
    except ValueError as exc:
        raise ManifestError(f"{path} is not JSON: {exc}") from exc
    return parse_manifest(document)
