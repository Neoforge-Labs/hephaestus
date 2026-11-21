"""Dataset manifests and the digest scope (spec section 10).

Expected hashes in the *vectors* come from the RFC 8785 reference package; the
tests here pin the composition (`data_hash` is `content_hash` of the sorted
digest array, nothing else) by recomputing it from `hephkit.hashing`, which is
the kit's own already-pinned primitive, and pin the behaviour around it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from hephkit.errors import LAB_412
from hephkit.hashing import content_hash
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
from hephkit.lab.repro import ContentHash

META = {
    "dataset": "demo",
    "source": "https://example.org/demo",
    "release": "2026-01",
    "extractor_version": "0.1.0",
    "captured_at": date(2026, 2, 3),
}


def write_tree(root: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def build(root: Path) -> Manifest:
    return manifest_for(root, **META)  # type: ignore[arg-type]


def digest(path: str, data: bytes) -> dict[str, object]:
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def document(files: list[dict[str, object]]) -> dict[str, object]:
    return {**META, "captured_at": "2026-02-03", "files": files}


def test_the_data_hash_is_order_independent_over_paths(tmp_path: Path) -> None:
    forward = write_tree(tmp_path / "f", {"a.csv": b"1\n", "b.csv": b"2\n", "c/d.csv": b"3\n"})
    backward = write_tree(tmp_path / "b", {"c/d.csv": b"3\n", "b.csv": b"2\n", "a.csv": b"1\n"})
    assert data_hash(build(forward)) == data_hash(build(backward))


def test_the_walk_order_does_not_reach_the_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = write_tree(tmp_path, {"a.csv": b"1\n", "b.csv": b"2\n", "c/d.csv": b"3\n", "c/e.csv": b"4\n"})
    first = build(root)
    original = Path.iterdir

    def reversed_iterdir(self: Path):  # type: ignore[no-untyped-def]
        return iter(sorted(original(self), reverse=True))

    monkeypatch.setattr(Path, "iterdir", reversed_iterdir)
    second = build(root)
    assert data_hash(first) == data_hash(second)
    assert [f.path for f in first.files] == [f.path for f in second.files]


def test_the_data_hash_changes_when_a_file_is_renamed(tmp_path: Path) -> None:
    one = write_tree(tmp_path / "one", {"a.csv": b"same\n"})
    two = write_tree(tmp_path / "two", {"b.csv": b"same\n"})
    assert data_hash(build(one)) != data_hash(build(two))


def test_the_data_hash_changes_when_a_byte_changes(tmp_path: Path) -> None:
    one = write_tree(tmp_path / "one", {"a.csv": b"same\n"})
    two = write_tree(tmp_path / "two", {"a.csv": b"sane\n"})
    assert data_hash(build(one)) != data_hash(build(two))


def test_the_data_hash_is_the_content_hash_of_the_sorted_digest_array(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {"B.csv": b"x", "a.csv": b"yy", "dir/x.csv": b"z", "dir.x.csv": b"w"})
    manifest = build(root)
    ordered = sorted(manifest.files, key=lambda f: f.path.encode())
    assert [f.path for f in ordered] == ["B.csv", "a.csv", "dir.x.csv", "dir/x.csv"]
    assert data_hash(manifest) == content_hash([d.model_dump() for d in ordered])
    assert TypeAdapter(ContentHash).validate_python(data_hash(manifest)) == data_hash(manifest)


def test_a_manifest_listed_out_of_order_hashes_as_sorted() -> None:
    a, b = digest("a.csv", b"1"), digest("b.csv", b"2")
    assert data_hash(parse_manifest(document([b, a]))) == data_hash(parse_manifest(document([a, b])))


def test_the_data_hash_is_taken_over_the_digests_alone(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {"a.csv": b"1\n"})
    renamed = Manifest(**{**META, "dataset": "other", "release": "9"}, files=build(root).files)  # type: ignore[arg-type]
    assert data_hash(renamed) == data_hash(build(root))


def test_a_single_file_dataset_is_an_array_of_one(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {"only.bin": b"\x00\x01"})
    (only,) = build(root).files
    assert data_hash(build(root)) == content_hash([only.model_dump()])


def test_digest_file_is_relative_and_posix(tmp_path: Path) -> None:
    write_tree(tmp_path, {"sub/f.bin": b"abc"})
    got = digest_file(tmp_path / "sub" / "f.bin", relative_to=tmp_path)
    assert got == FileDigest(path="sub/f.bin", sha256=hashlib.sha256(b"abc").hexdigest(), bytes=3)


def test_an_empty_file_is_a_file(tmp_path: Path) -> None:
    write_tree(tmp_path, {"empty.txt": b""})
    (entry,) = build(tmp_path).files
    assert entry.bytes == 0
    assert entry.sha256 == hashlib.sha256(b"").hexdigest()


def test_a_directory_with_no_files_cannot_make_a_manifest(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(ManifestError) as exc:
        build(tmp_path)
    assert exc.value.code == LAB_412


def test_a_manifest_with_no_files_is_refused() -> None:
    with pytest.raises(ManifestError) as exc:
        parse_manifest(document([]))
    assert exc.value.code == LAB_412
    with pytest.raises(ValidationError):
        Manifest(**META, files=())  # type: ignore[arg-type]


def test_a_duplicate_path_is_refused() -> None:
    with pytest.raises(ManifestError, match="duplicate"):
        parse_manifest(document([digest("a.csv", b"1"), digest("a.csv", b"2")]))


@pytest.mark.parametrize(
    "bad",
    ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "", ("a" * 64) + "\n"],
    ids=["uppercase", "short", "long", "not-hex", "empty", "trailing-newline"],
)
def test_a_sha256_that_is_not_64_hex_characters_is_refused(bad: str) -> None:
    entry = {**digest("a.csv", b"1"), "sha256": bad}
    with pytest.raises(ManifestError):
        parse_manifest(document([entry]))


@pytest.mark.parametrize("bad", [-1, 1.5, "3", True], ids=["negative", "float", "string", "bool"])
def test_bytes_must_be_a_non_negative_integer(bad: object) -> None:
    with pytest.raises(ManifestError):
        parse_manifest(document([{**digest("a.csv", b"1"), "bytes": bad}]))


@pytest.mark.parametrize(
    "bad",
    [0, 1764000000, 1.5, True, None, [], {}, "not-a-date"],
    ids=["epoch", "unix-seconds", "float", "bool", "null", "array", "object", "non-date-string"],
)
def test_a_captured_at_that_is_not_a_date_is_refused(bad: object) -> None:
    """10.4: a member whose type is not 10.1's is invalid, not coerced.

    Read off the clause, not off the code: 10.1 gives `captured_at` as an
    RFC 3339 `full-date` string, so a number is not a date and MUST NOT be read
    as one. Pydantic's lax mode would read `0` as 1970-01-01 and the manifest
    would then describe a capture that never happened.
    """
    with pytest.raises(ManifestError) as exc:
        parse_manifest({**document([digest("a.csv", b"1")]), "captured_at": bad})
    assert exc.value.code == LAB_412


def test_a_captured_at_that_is_a_datetime_is_refused_not_truncated() -> None:
    """A `datetime` is a `date` subclass, and 10.1's type is a calendar date."""
    with pytest.raises(ValidationError, match="full-date"):
        Manifest(
            **{**META, "captured_at": datetime(2026, 2, 3, 0, 0)},  # type: ignore[arg-type]
            files=(FileDigest(path="a.csv", sha256="a" * 64, bytes=1),),
        )


def test_the_two_forms_a_captured_at_may_take_are_both_accepted() -> None:
    """The refusal must not have closed the door on the string 10.1 asks for."""
    from_json = parse_manifest(document([digest("a.csv", b"1")]))
    assert from_json.captured_at == date(2026, 2, 3)
    assert from_json.captured_at == Manifest(
        **META,  # type: ignore[arg-type]
        files=from_json.files,
    ).captured_at


def test_bytes_disagreeing_with_the_file_is_refused(tmp_path: Path) -> None:
    write_tree(tmp_path, {"a.csv": b"12345"})
    wrong = parse_manifest(document([{**digest("a.csv", b"12345"), "bytes": 6}]))
    with pytest.raises(ManifestError, match="a.csv") as exc:
        verify_manifest(wrong, tmp_path)
    assert exc.value.code == LAB_412
    verify_manifest(parse_manifest(document([digest("a.csv", b"12345")])), tmp_path)


@pytest.mark.parametrize(
    "bad",
    ["/etc/passwd", "../a.csv", "d/../a.csv", "./a.csv", "d/./a.csv", "d//a.csv", "d/", ""],
    ids=["absolute", "dotdot", "dotdot-inside", "dot", "dot-inside", "empty-segment", "trailing", "empty"],
)
def test_a_path_that_is_not_relative_within_the_dataset_is_refused(bad: str) -> None:
    with pytest.raises(ManifestError) as exc:
        parse_manifest(document([{**digest("a.csv", b"1"), "path": bad}]))
    assert exc.value.code == LAB_412
    with pytest.raises(ValidationError):
        FileDigest(path=bad, sha256="a" * 64, bytes=0)


def test_a_dotted_name_is_not_a_dot_segment() -> None:
    for ok in ("..a", "a..", ".hidden", "d/.hidden/f", "a b/c"):
        FileDigest(path=ok, sha256="a" * 64, bytes=0)


def test_digest_file_outside_the_root_is_a_manifest_error(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.bin").write_bytes(b"x")
    with pytest.raises(ManifestError) as exc:
        digest_file(tmp_path / "outside.bin", relative_to=root)
    assert exc.value.code == LAB_412
    with pytest.raises(ManifestError):
        digest_file(root / ".." / "outside.bin", relative_to=root)


def test_verify_manifest_does_not_flag_files_the_manifest_omits(tmp_path: Path) -> None:
    write_tree(tmp_path, {"a.csv": b"1", "extra.csv": b"2"})
    verify_manifest(parse_manifest(document([digest("a.csv", b"1")])), tmp_path)


def test_a_sha256_disagreeing_with_the_file_is_refused(tmp_path: Path) -> None:
    write_tree(tmp_path, {"a.csv": b"12345"})
    wrong = parse_manifest(document([digest("a.csv", b"12346")]))
    assert wrong.files[0].bytes == 5
    with pytest.raises(ManifestError, match="sha256") as exc:
        verify_manifest(wrong, tmp_path)
    assert exc.value.code == LAB_412


def test_a_file_the_manifest_names_but_the_root_lacks_is_refused(tmp_path: Path) -> None:
    manifest = parse_manifest(document([digest("gone.csv", b"1")]))
    with pytest.raises(ManifestError, match="gone.csv"):
        verify_manifest(manifest, tmp_path)


def test_an_undefined_or_missing_member_is_refused() -> None:
    with pytest.raises(ManifestError):
        parse_manifest(document([{**digest("a.csv", b"1"), "mtime": 0}]))
    with pytest.raises(ManifestError):
        parse_manifest(document([{"path": "a.csv", "sha256": "a" * 64}]))
    with pytest.raises(ManifestError):
        parse_manifest({**document([digest("a.csv", b"1")]), "license": "cc0"})
    gap = document([digest("a.csv", b"1")])
    del gap["release"]
    with pytest.raises(ManifestError):
        parse_manifest(gap)


def test_a_manifest_round_trips_through_disk(tmp_path: Path) -> None:
    manifest = build(write_tree(tmp_path / "data", {"a.csv": b"1\n", "z/b.csv": b"22\n"}))
    target = tmp_path / "out" / "manifest.json"
    assert write_manifest(manifest, target) == target
    assert read_manifest(target) == manifest
    assert data_hash(read_manifest(target)) == data_hash(manifest)


def test_reading_an_absent_manifest_is_not_an_invalid_one(tmp_path: Path) -> None:
    with pytest.raises(MissingManifestError) as exc:
        read_manifest(tmp_path / "nope.json")
    assert exc.value.code != LAB_412
    assert isinstance(exc.value, ManifestError)


@pytest.mark.parametrize("text", ["{not json", "[]", "3"], ids=["malformed", "array", "scalar"])
def test_a_manifest_file_that_is_not_an_object_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "m.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ManifestError) as exc:
        read_manifest(path)
    assert exc.value.code == LAB_412


def test_as_document_writes_section_10_1s_members_in_order() -> None:
    manifest = parse_manifest(document([digest("a.csv", b"1")]))
    doc = manifest.as_document()
    assert list(doc) == ["dataset", "source", "release", "extractor_version", "captured_at", "files"]
    assert doc["captured_at"] == "2026-02-03"
    assert list(doc["files"][0]) == ["path", "sha256", "bytes"]
    json.dumps(doc)


def test_file_digest_is_strict_and_frozen() -> None:
    entry = FileDigest(path="a", sha256="a" * 64, bytes=0)
    with pytest.raises(ValidationError):
        entry.path = "b"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        FileDigest(path="a", sha256="a" * 64, bytes="0")  # type: ignore[arg-type]
