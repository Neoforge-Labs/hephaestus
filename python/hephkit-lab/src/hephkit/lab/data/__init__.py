"""Frozen, content-addressed datasets: a number cannot exist without an identifiable input.

`hephkit.lab.data` is the data half of the integrity spine. This portion holds
the dataset manifest and the digest scope of spec section 10: what a manifest
carries, and how its files collapse to the `data_hash` a provenance record
(spec 7.1) names. It also resolves a date to the release that date would have
seen (10.3).

Maturity: experimental.
"""

from __future__ import annotations

from hephkit.lab.data.manifest import (
    FileDigest,
    Manifest,
    ManifestError,
    MissingManifestError,
    data_hash,
    digest_file,
    manifest_for,
    parse_manifest,
    read_manifest,
    verify_manifest,
    write_manifest,
)
from hephkit.lab.data.releases import AmbiguousReleaseError, Release, TemporalError, release_as_of

__all__ = [
    "AmbiguousReleaseError",
    "FileDigest",
    "Manifest",
    "ManifestError",
    "MissingManifestError",
    "Release",
    "TemporalError",
    "data_hash",
    "digest_file",
    "manifest_for",
    "parse_manifest",
    "read_manifest",
    "release_as_of",
    "verify_manifest",
    "write_manifest",
]
