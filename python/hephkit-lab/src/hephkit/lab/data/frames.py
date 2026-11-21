"""Frame loaders over a manifest: read what it names, after checking what it says.

Both loaders verify a file against the manifest *before* reading it
(:func:`~hephkit.lab.data.manifest.verify_manifest`, spec 10.4), so a file whose
bytes moved since the manifest was written is refused with ``HEPH-LAB-412`` and
no frame is ever built from it. That is the point of the module: a number cannot
come from a dataset that is not the one the provenance record names.

Polars and DuckDB live behind the ``data`` extra (ADR 0023), so neither is
imported at module scope. Each is imported inside the function that needs it,
through :func:`~hephkit.lab._extras.require`: a spine-only install can import
this module, and gets an error naming ``hephkit-lab[data]`` on first use.

Supported formats are ``.csv`` and ``.parquet``.

Verification is not atomic with the read: a writer that changes a file between
the two defeats it. A frozen dataset is read-only by construction (spec 10); a
directory something else is writing to is outside what this guards.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hephkit.lab._extras import require
from hephkit.lab.data.manifest import FileDigest, Manifest, ManifestError, verify_manifest

if TYPE_CHECKING:
    import polars as pl

__all__ = ["query", "read_frame"]

_FORMATS = (".csv", ".parquet")


def _only(manifest: Manifest, entry: FileDigest) -> Manifest:
    """``manifest`` narrowed to one entry, so verification touches only that file."""
    return manifest.model_copy(update={"files": (entry,)})


def _sql_identifier(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def read_frame(manifest: Manifest, *, root: Path, file: str | None = None) -> pl.DataFrame:
    """Read one file of ``manifest`` as a polars frame, after verifying its digest.

    ``file`` is the manifest ``path`` of the file; it may be omitted only when
    the manifest lists exactly one. A path the manifest does not list is
    refused (``ManifestError``) even if the file is on disk, and so is a file
    whose bytes disagree with the manifest.
    """
    polars = require("polars", extra="data")
    if file is None:
        if len(manifest.files) != 1:
            raise ValueError(f"the manifest lists {len(manifest.files)} files; name one with file=")
        entry = manifest.files[0]
    else:
        named = [f for f in manifest.files if f.path == file]
        if not named:
            raise ManifestError(f"the manifest does not name {file!r}")
        entry = named[0]
    suffix = Path(entry.path).suffix
    if suffix not in _FORMATS:
        raise ValueError(f"{entry.path!r}: cannot read a {suffix or 'suffixless'} file as a frame")
    verify_manifest(_only(manifest, entry), root)
    # A handle, never the path string: polars treats a path as a glob pattern, so
    # a manifest-named `x*.csv` would pull in an unlisted `xother.csv`.
    with (root / entry.path).open("rb") as handle:
        frame: pl.DataFrame = (
            polars.read_parquet(handle) if suffix == ".parquet" else polars.read_csv(handle)
        )
    return frame


def query(manifest: Manifest, *, root: Path, sql: str) -> pl.DataFrame:
    """Run ``sql`` in DuckDB over the manifest's tabular files, each a table named by its ``path``.

    A caller writes ``SELECT ... FROM "raw/a.csv"``: the name is the manifest's
    ``path``, verbatim. Every file the manifest names is verified first, so the
    query never runs against bytes the manifest does not describe; files the
    manifest omits cannot be queried, nor can anything else on disk. Entries that are
    not ``.csv`` or ``.parquet`` are verified but not exposed.
    """
    require("polars", extra="data")
    duckdb = require("duckdb", extra="data")
    verify_manifest(manifest, root)
    connection = duckdb.connect(":memory:")
    try:
        for entry in manifest.files:
            suffix = Path(entry.path).suffix
            if suffix not in _FORMATS:
                continue
            # DuckDB is handed the open file, never its path: `read_csv` and
            # `read_parquet` glob a path string, so a manifest-named `x*.csv`
            # would load an unlisted `xother.csv` that no digest covers.
            with (root / entry.path).open("rb") as handle:
                relation = (
                    connection.read_parquet(handle)
                    if suffix == ".parquet"
                    else connection.read_csv(handle)
                )
                connection.execute(
                    f"CREATE TABLE {_sql_identifier(entry.path)} AS SELECT * FROM relation"
                )
        # Loaded as tables, then the door is shut: with external access on, DuckDB
        # resolves a bare file name or `read_csv('...')` straight from disk, so a
        # file the manifest omits (or any file the process can read) would be
        # queryable and unverified.
        connection.execute("SET enable_external_access = false")
        # DuckDB's own typing, via its Arrow bridge: an integer column holding a
        # null stays an integer, a DECIMAL stays a decimal. Rebuilding the frame
        # from Python rows would leave polars to guess every dtype from whichever
        # rows the query happened to return.
        result = connection.sql(sql)
        if result is None:
            raise ValueError("query() needs a statement that returns rows, not DDL or a SET")
        frame: pl.DataFrame = result.pl()
    finally:
        connection.close()
    return frame
