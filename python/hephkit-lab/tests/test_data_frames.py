"""Frame loaders over a manifest: they read what the manifest names, and only after verifying it.

The refusal tests are the ones that matter: a wrong number must never reach a
caller, so a file whose bytes moved after the manifest was written has to fail
*before* a frame exists, not after.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

from hephkit.lab._extras import MissingExtraError
from hephkit.lab.data.frames import query, read_frame
from hephkit.lab.data.manifest import Manifest, ManifestError, manifest_for

META = {
    "dataset": "demo",
    "source": "https://example.org/demo",
    "release": "2026-01",
    "extractor_version": "0.1.0",
    "captured_at": date(2026, 2, 3),
}

CSV_A = b"id,value\n1,10\n2,20\n3,30\n"
CSV_B = b"id,label\n1,x\n2,y\n"


def build(root: Path, files: dict[str, bytes]) -> Manifest:
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return manifest_for(root, **META)  # type: ignore[arg-type]


@pytest.mark.extras
def test_read_frame_reads_the_file_the_manifest_names(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": CSV_A})
    frame = read_frame(manifest, root=tmp_path)
    assert frame.columns == ["id", "value"]
    assert frame["value"].to_list() == [10, 20, 30]


@pytest.mark.extras
def test_read_frame_reads_a_named_file_and_a_parquet_file(tmp_path: Path) -> None:
    import polars as pl

    (tmp_path / "sub").mkdir()
    pl.DataFrame({"k": [1, 2]}).write_parquet(tmp_path / "sub" / "p.parquet")
    manifest = build(tmp_path, {"a.csv": CSV_A, "b.csv": CSV_B})
    assert read_frame(manifest, root=tmp_path, file="b.csv")["label"].to_list() == ["x", "y"]
    assert read_frame(manifest, root=tmp_path, file="sub/p.parquet")["k"].to_list() == [1, 2]


@pytest.mark.extras
def test_read_frame_refuses_a_file_whose_digest_moved(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": CSV_A})
    # Same length, one byte different: the size check alone would let this through.
    (tmp_path / "a.csv").write_bytes(CSV_A.replace(b"20", b"21"))
    with pytest.raises(ManifestError) as exc:
        read_frame(manifest, root=tmp_path)
    assert exc.value.code == "HEPH-LAB-412"


@pytest.mark.extras
def test_a_refused_file_never_reaches_the_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    manifest = build(tmp_path, {"a.csv": CSV_A})
    (tmp_path / "a.csv").write_bytes(CSV_A + b"4,40\n")

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("polars read a file the manifest does not describe")

    monkeypatch.setattr(pl, "read_csv", boom)
    with pytest.raises(ManifestError):
        read_frame(manifest, root=tmp_path)


@pytest.mark.extras
def test_a_file_absent_from_the_manifest_is_not_readable(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": CSV_A})
    (tmp_path / "stray.csv").write_bytes(b"id\n9\n")
    with pytest.raises(ManifestError, match="stray.csv"):
        read_frame(manifest, root=tmp_path, file="stray.csv")


@pytest.mark.extras
def test_read_frame_needs_a_file_name_when_the_manifest_has_several(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": CSV_A, "b.csv": CSV_B})
    with pytest.raises(ValueError, match="file="):
        read_frame(manifest, root=tmp_path)


@pytest.mark.extras
def test_read_frame_refuses_a_format_it_cannot_read(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"notes.txt": b"hello\n"})
    with pytest.raises(ValueError, match="notes.txt"):
        read_frame(manifest, root=tmp_path)


@pytest.mark.extras
def test_query_sees_every_file_in_the_manifest(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": CSV_A, "nested/b.csv": CSV_B})
    frame = query(
        manifest,
        root=tmp_path,
        sql='SELECT a.id, a.value, b.label FROM "a.csv" a JOIN "nested/b.csv" b USING (id) ORDER BY id',
    )
    assert frame.columns == ["id", "value", "label"]
    assert frame.rows() == [(1, 10, "x"), (2, 20, "y")]


@pytest.mark.extras
def test_query_refuses_a_moved_file_before_running_anything(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": CSV_A})
    (tmp_path / "a.csv").write_bytes(CSV_A.replace(b"30", b"31"))
    with pytest.raises(ManifestError):
        query(manifest, root=tmp_path, sql='SELECT sum(value) FROM "a.csv"')


@pytest.mark.extras
def test_query_cannot_see_a_file_the_manifest_omits(tmp_path: Path) -> None:
    import duckdb

    manifest = build(tmp_path, {"a.csv": CSV_A})
    (tmp_path / "stray.csv").write_bytes(b"id\n9\n")
    # DuckDB would otherwise resolve a bare file name, or read_csv('...'), straight
    # from disk: external access is shut once the manifest's files are loaded.
    for sql in (
        'SELECT * FROM "stray.csv"',
        f"SELECT * FROM read_csv('{tmp_path / 'stray.csv'}')",
    ):
        with pytest.raises(duckdb.Error):
            query(manifest, root=tmp_path, sql=sql)


@pytest.mark.extras
def test_query_handles_parquet_a_name_with_a_quote_and_a_non_tabular_entry(
    tmp_path: Path,
) -> None:
    import polars as pl

    pl.DataFrame({"n": [1, 2, 3]}).write_parquet(tmp_path / "it's.parquet")
    (tmp_path / "README.txt").write_bytes(b"not a table\n")
    manifest = manifest_for(tmp_path, **META)  # type: ignore[arg-type]
    frame = query(manifest, root=tmp_path, sql='SELECT sum(n) AS s FROM "it\'s.parquet"')
    assert frame["s"].to_list() == [6]


def test_the_module_imports_and_names_the_extra_when_polars_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spine-safe: importing `frames` needs no extra; using it names the one to install."""
    manifest = build(tmp_path, {"a.csv": CSV_A})
    monkeypatch.setitem(sys.modules, "polars", None)
    monkeypatch.setitem(sys.modules, "duckdb", None)
    with pytest.raises(MissingExtraError, match=r"hephkit-lab\[data\]"):
        read_frame(manifest, root=tmp_path)
    with pytest.raises(MissingExtraError, match=r"hephkit-lab\[data\]"):
        query(manifest, root=tmp_path, sql="SELECT 1")
