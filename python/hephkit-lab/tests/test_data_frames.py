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
def test_the_name_query_loads_through_is_not_left_for_the_callers_sql(tmp_path: Path) -> None:
    """Each file is registered under a fixed internal name and unregistered again.

    Two things to hold. A manifest `path` with a directory in it must still
    become a table of exactly that name -- `relation.create(path)` would read
    `nested/b.csv` as schema `nested` -- and the name used to get it in must be
    gone before the caller's SQL runs, or the last file loaded would be
    queryable under a name the manifest never gave.
    """
    import duckdb

    manifest = build(tmp_path, {"nested/b.csv": CSV_B})
    assert query(manifest, root=tmp_path, sql='SELECT count(*) AS n FROM "nested/b.csv"')[
        "n"
    ].to_list() == [2]
    with pytest.raises(duckdb.CatalogException):
        query(manifest, root=tmp_path, sql="SELECT * FROM _hephkit_manifest_source")


@pytest.mark.extras
def test_query_refuses_a_moved_file_before_running_anything(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"a.csv": CSV_A})
    (tmp_path / "a.csv").write_bytes(CSV_A.replace(b"30", b"31"))
    with pytest.raises(ManifestError):
        query(manifest, root=tmp_path, sql='SELECT sum(value) FROM "a.csv"')


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


@pytest.mark.extras
def test_query_keeps_the_dtypes_duckdb_assigned(tmp_path: Path) -> None:
    """Types are DuckDB's, not polars' guess from the rows that came back."""
    import polars as pl

    manifest = build(tmp_path, {"t.csv": b"n,d\n1,2026-01-02\n,2026-01-03\n"})
    frame = query(
        manifest,
        root=tmp_path,
        sql=(
            'SELECT n, d, CAST(1.50 AS DECIMAL(10, 2)) AS money, '
            'CAST(NULL AS INTEGER) AS nothing FROM "t.csv"'
        ),
    )
    assert frame["n"].dtype.is_integer(), "an integer column holding a null must stay an integer"
    assert frame["n"].to_list() == [1, None]
    assert frame["d"].dtype == pl.Date
    assert isinstance(frame["money"].dtype, pl.Decimal), "a DECIMAL must not become a float"
    assert frame["money"].dtype.scale == 2
    assert frame["nothing"].dtype.is_integer(), "an all-null column keeps its declared type"


@pytest.mark.extras
def test_read_frame_does_not_glob_a_manifest_path(tmp_path: Path) -> None:
    """A manifest-named `x*.csv` must not pull in the unlisted `xother.csv`."""
    manifest = build(tmp_path, {"x*.csv": b"n\n1\n2\n"})
    (tmp_path / "xother.csv").write_bytes(b"n\n99\n")
    assert read_frame(manifest, root=tmp_path)["n"].to_list() == [1, 2]


@pytest.mark.extras
def test_query_does_not_glob_a_manifest_path(tmp_path: Path) -> None:
    manifest = build(tmp_path, {"x*.csv": b"n\n1\n2\n", "p[1].csv": b"n\n5\n"})
    (tmp_path / "xother.csv").write_bytes(b"n\n99\n")
    (tmp_path / "p1.csv").write_bytes(b"n\n77\n")
    frame = query(
        manifest, root=tmp_path, sql='SELECT n FROM "x*.csv" UNION ALL SELECT n FROM "p[1].csv" ORDER BY n'
    )
    assert frame["n"].to_list() == [1, 2, 5]


@pytest.mark.extras
def test_read_frame_refuses_a_parquet_file_whose_digest_moved(tmp_path: Path) -> None:
    import polars as pl

    pl.DataFrame({"k": [1, 2, 3]}).write_parquet(tmp_path / "p.parquet")
    manifest = manifest_for(tmp_path, **META)  # type: ignore[arg-type]
    data = bytearray((tmp_path / "p.parquet").read_bytes())
    data[len(data) // 2] ^= 0x01
    (tmp_path / "p.parquet").write_bytes(bytes(data))
    with pytest.raises(ManifestError):
        read_frame(manifest, root=tmp_path)


@pytest.mark.extras
@pytest.mark.parametrize(
    "template",
    [
        "ATTACH '{stray}' AS other",
        "SELECT * FROM glob('{dir}/*')",
        "COPY (SELECT 1 AS n) TO '{dir}/out.csv'",
        "SET enable_external_access = true",
        "SELECT * FROM read_csv('{stray}')",
        'SELECT * FROM "stray.csv"',
    ],
)
def test_caller_sql_cannot_reach_the_filesystem(tmp_path: Path, template: str) -> None:
    import duckdb

    manifest = build(tmp_path, {"a.csv": CSV_A})
    stray = tmp_path / "stray.csv"
    stray.write_bytes(b"id\n9\n")
    with pytest.raises(duckdb.Error):
        query(manifest, root=tmp_path, sql=template.format(stray=stray, dir=tmp_path))
    assert not (tmp_path / "out.csv").exists()


@pytest.mark.extras
def test_query_refuses_a_statement_that_returns_no_relation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DuckDB 1.x returns None for DDL; 2.x does not. The guard must hold on both."""
    import duckdb

    real_connect = duckdb.connect

    class NoRelation:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

        def sql(self, *args: object, **kwargs: object) -> None:
            return None

    monkeypatch.setattr(duckdb, "connect", lambda *a, **k: NoRelation(real_connect(*a, **k)))
    manifest = build(tmp_path, {"a.csv": CSV_A})
    with pytest.raises(ValueError, match="returns rows"):
        query(manifest, root=tmp_path, sql="CREATE TABLE t (a INTEGER)")


@pytest.mark.extras
def test_paths_differing_only_by_case_fail_loudly(tmp_path: Path) -> None:
    """DuckDB's catalog is case-insensitive, so `A.csv` and `a.csv` collide. Never silently."""
    import duckdb

    from hephkit.lab.data.manifest import FileDigest

    (tmp_path / "a.csv").write_bytes(CSV_A)
    if not (tmp_path / "A.csv").exists():  # a case-sensitive filesystem
        (tmp_path / "A.csv").write_bytes(CSV_A)
    one = manifest_for(tmp_path, **META)  # type: ignore[arg-type]
    digest = one.files[0]
    manifest = one.model_copy(
        update={
            "files": (
                FileDigest(path="a.csv", sha256=digest.sha256, bytes=digest.bytes),
                FileDigest(path="A.csv", sha256=digest.sha256, bytes=digest.bytes),
            )
        }
    )
    with pytest.raises(duckdb.CatalogException):
        query(manifest, root=tmp_path, sql='SELECT * FROM "a.csv"')
