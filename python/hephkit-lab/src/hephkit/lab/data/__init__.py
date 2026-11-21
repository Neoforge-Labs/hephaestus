"""Frozen, content-addressed datasets: a number cannot exist without an identifiable input.

`hephkit.lab.data` is the data half of the integrity spine. This portion holds
the dataset manifest and the digest scope of spec section 10: what a manifest
carries, and how its files collapse to the `data_hash` a provenance record
(spec 7.1) names. It also resolves a date to the release that date would have
seen (10.3), reads the files a manifest names as frames, snapshots them to a
DVC remote, and renders the data card.

Maturity: experimental.
"""

from __future__ import annotations

from hephkit.lab.data.cards import data_card
from hephkit.lab.data.frames import query, read_frame
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
from hephkit.lab.data.snapshots import UnsupportedDvcLayoutError, pull, push

__all__ = [
    "AmbiguousReleaseError",
    "FileDigest",
    "Manifest",
    "ManifestError",
    "MissingManifestError",
    "Release",
    "TemporalError",
    "UnsupportedDvcLayoutError",
    "data_card",
    "data_hash",
    "digest_file",
    "manifest_for",
    "parse_manifest",
    "pull",
    "push",
    "query",
    "read_frame",
    "read_manifest",
    "release_as_of",
    "verify_manifest",
    "write_manifest",
]
