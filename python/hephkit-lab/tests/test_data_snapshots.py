"""DVC snapshots of a manifest's files, over a local directory remote.

A directory remote needs no daemon, credentials or S3, and what is under test
(a snapshot round-trips; a corrupted arrival is refused) does not depend on the
object-store protocol. The refusal tests corrupt what is *in the remote*, not
the happy path, because `pull` is the one function here that handles bytes it
did not write.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from hephkit.errors import LAB_412, LAB_424
from hephkit.lab.data.manifest import Manifest, ManifestError, MissingManifestError, manifest_for

META = {
    "dataset": "demo",
    "source": "https://example.org/demo",
    "release": "2026-01",
    "extractor_version": "0.1.0",
    "captured_at": date(2026, 2, 3),
}

FILES = {"a.csv": b"id,v\n1,10\n2,20\n", "raw/b.csv": b"id,l\n1,x\n"}


def build(root: Path, files: dict[str, bytes] | None = None) -> Manifest:
    for name, data in (files or FILES).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return manifest_for(root, **META)  # type: ignore[arg-type]


@contextmanager
def refused(match: str | None = None) -> Iterator[None]:
    """Expect an integrity refusal: ``HEPH-LAB-412``, and not its 424 subclass.

    ``MissingManifestError`` is a ``ManifestError``, so a bare ``pytest.raises``
    could not tell the two apart.
    """
    with pytest.raises(ManifestError, match=match) as caught:
        yield
    assert caught.value.code == LAB_412
    assert not isinstance(caught.value, MissingManifestError)


def listing(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def remote_objects(remote: Path) -> list[Path]:
    """The DVC objects in a directory remote, not the snapshot pointers beside them."""
    return [
        p
        for p in (remote / "files" / "md5").rglob("*")
        if p.is_file() and "snapshots" not in p.parts
    ]


def corrupt(remote: Path, original: bytes, replacement: bytes) -> None:
    victim = next(p for p in remote_objects(remote) if p.read_bytes() == original)
    victim.chmod(0o644)  # DVC stores its objects read-only
    victim.write_bytes(replacement)


@pytest.mark.extras
def test_a_pushed_snapshot_pulls_back_byte_identical(tmp_path: Path) -> None:
    from hephkit.lab.data.snapshots import pull, push

    source, remote, target = tmp_path / "src", tmp_path / "remote", tmp_path / "dst"
    manifest = build(source)
    push(manifest, root=source, remote=str(remote))
    pull(manifest, into=target, remote=str(remote))
    assert listing(target) == FILES
    assert not (source / ".dvc").exists()  # the caller's directory is not turned into a DVC repo
    assert not (target / ".dvc").exists()


@pytest.mark.extras
def test_push_does_not_send_a_file_the_manifest_omits(tmp_path: Path) -> None:
    from hephkit.lab.data.snapshots import pull, push

    source, remote, target = tmp_path / "src", tmp_path / "remote", tmp_path / "dst"
    manifest = build(source)
    (source / "unlisted.csv").write_bytes(b"secret\n")
    push(manifest, root=source, remote=str(remote))
    assert all(p.read_bytes() != b"secret\n" for p in remote_objects(remote))
    pull(manifest, into=target, remote=str(remote))
    assert "unlisted.csv" not in listing(target)


@pytest.mark.extras
def test_push_refuses_a_root_that_disagrees_with_the_manifest(tmp_path: Path) -> None:
    from hephkit.lab.data.snapshots import push

    source, remote = tmp_path / "src", tmp_path / "remote"
    manifest = build(source)
    (source / "a.csv").write_bytes(b"id,v\n1,99\n2,20\n")
    with refused(match="a.csv"):
        push(manifest, root=source, remote=str(remote))
    assert not remote.exists()


@pytest.mark.extras
def test_a_pull_whose_arrival_disagrees_with_the_manifest_is_refused(tmp_path: Path) -> None:
    from hephkit.lab.data.snapshots import pull, push

    source, remote, target = tmp_path / "src", tmp_path / "remote", tmp_path / "dst"
    manifest = build(source)
    push(manifest, root=source, remote=str(remote))
    # Same length, different content: what arrives is the right shape and the wrong bytes.
    corrupt(remote, FILES["a.csv"], b"id,v\n1,11\n2,20\n")
    with pytest.raises(ManifestError) as caught:
        pull(manifest, into=target, remote=str(remote))
    assert caught.value.code == LAB_412
    assert "a.csv" in str(caught.value)


@pytest.mark.extras
def test_a_pull_whose_remote_lost_an_object_is_refused(tmp_path: Path) -> None:
    from hephkit.lab.data.snapshots import pull, push

    source, remote, target = tmp_path / "src", tmp_path / "remote", tmp_path / "dst"
    manifest = build(source)
    push(manifest, root=source, remote=str(remote))
    victim = next(p for p in remote_objects(remote) if p.read_bytes() == FILES["raw/b.csv"])
    victim.chmod(0o644)
    victim.unlink()
    # An object DVC cannot fetch is a dependency that is absent (424), not a
    # digest that disagrees (412).
    with pytest.raises(MissingManifestError) as caught:
        pull(manifest, into=target, remote=str(remote))
    assert caught.value.code == LAB_424
    assert not target.exists() or listing(target) == {}


@pytest.mark.extras
def test_a_pull_from_a_remote_that_does_not_exist_is_missing_not_corrupt(tmp_path: Path) -> None:
    from hephkit.lab.data.snapshots import pull

    manifest = build(tmp_path / "src")
    absent = tmp_path / "no-such-remote"
    with pytest.raises(MissingManifestError) as caught:
        pull(manifest, into=tmp_path / "dst", remote=str(absent))
    assert caught.value.code == LAB_424
    assert str(absent) in str(caught.value)


@pytest.mark.extras
def test_a_pull_from_an_unreachable_remote_url_is_missing_not_corrupt(tmp_path: Path) -> None:
    """A DVC failure while obtaining the snapshot is 424 whatever the transport."""
    from hephkit.lab.data.snapshots import pull

    manifest = build(tmp_path / "src")
    with pytest.raises(MissingManifestError) as caught:
        pull(manifest, into=tmp_path / "dst", remote="notaprotocol://nowhere/bucket")
    assert caught.value.code == LAB_424
    assert "notaprotocol://nowhere/bucket" in str(caught.value)


@pytest.mark.extras
def test_a_connection_failure_reading_the_pointer_is_missing_not_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A remote that is up in config but unreachable on the wire raises OSError, not DvcException."""
    from hephkit.lab.data import snapshots

    source, remote = tmp_path / "src", tmp_path / "remote"
    manifest = build(source)
    snapshots.push(manifest, root=source, remote=str(remote))

    def unreachable(self: object, path: str) -> bytes:
        raise ConnectionError("connection refused")

    monkeypatch.setattr("dvc_objects.fs.local.LocalFileSystem.cat_file", unreachable)
    with pytest.raises(MissingManifestError) as caught:
        snapshots.pull(manifest, into=tmp_path / "dst", remote=str(remote))
    assert caught.value.code == LAB_424
    assert str(remote) in str(caught.value)


@pytest.mark.extras
def test_a_failure_while_placing_a_file_leaves_no_temp_file_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hephkit.lab.data import snapshots

    source, remote, target = tmp_path / "src", tmp_path / "remote", tmp_path / "dst"
    manifest = build(source)
    snapshots.push(manifest, root=source, remote=str(remote))

    def full_disk(*args: object, **kwargs: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(snapshots.shutil, "copyfileobj", full_disk)
    with pytest.raises(OSError, match="no space"):
        snapshots.pull(manifest, into=target, remote=str(remote))
    assert [p for p in target.rglob("*") if p.is_file()] == []


@pytest.mark.extras
def test_an_arrival_that_is_a_symlink_is_refused_even_if_its_bytes_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard between a caller's directory and a link that came off a remote."""
    from hephkit.lab.data import snapshots

    source, remote, target = tmp_path / "src", tmp_path / "remote", tmp_path / "dst"
    manifest = build(source)
    snapshots.push(manifest, root=source, remote=str(remote))
    outside = tmp_path / "outside.csv"
    outside.write_bytes(FILES["a.csv"])  # right bytes, wrong place: verification alone would pass
    real_fetch = snapshots._fetch

    def fetch_then_link(*args: object, **kwargs: object) -> Path:
        arrived: Path = real_fetch(*args, **kwargs)  # type: ignore[arg-type]
        (arrived / "a.csv").unlink()
        (arrived / "a.csv").symlink_to(outside)
        return arrived

    monkeypatch.setattr(snapshots, "_fetch", fetch_then_link)
    with refused(match="arrived as a link"):
        snapshots.pull(manifest, into=target, remote=str(remote))
    assert not target.exists() or listing(target) == {}


@pytest.mark.extras
def test_an_arrival_whose_directory_is_a_symlink_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hephkit.lab.data import snapshots

    source, remote, target = tmp_path / "src", tmp_path / "remote", tmp_path / "dst"
    manifest = build(source)
    snapshots.push(manifest, root=source, remote=str(remote))
    elsewhere = tmp_path / "elsewhere"
    (elsewhere).mkdir()
    (elsewhere / "b.csv").write_bytes(FILES["raw/b.csv"])
    real_fetch = snapshots._fetch

    def fetch_then_link(*args: object, **kwargs: object) -> Path:
        arrived: Path = real_fetch(*args, **kwargs)  # type: ignore[arg-type]
        for child in (arrived / "raw").iterdir():
            child.unlink()
        (arrived / "raw").rmdir()
        (arrived / "raw").symlink_to(elsewhere, target_is_directory=True)
        return arrived

    monkeypatch.setattr(snapshots, "_fetch", fetch_then_link)
    with refused(match="arrived as a link"):
        snapshots.pull(manifest, into=target, remote=str(remote))


@pytest.mark.extras
def test_an_unexpected_remote_layout_fails_loudly_naming_the_dvc_version(tmp_path: Path) -> None:
    import dvc

    from hephkit.lab.data.snapshots import UnsupportedDvcLayoutError, _pointer_path

    class Odb:
        path = "bucket/some/other/layout"

    manifest = build(tmp_path / "src")
    with pytest.raises(UnsupportedDvcLayoutError) as caught:
        _pointer_path(Odb(), manifest)
    assert dvc.__version__ in str(caught.value)
    assert "files/md5" in str(caught.value)


@pytest.mark.extras
def test_an_error_outside_dvc_propagates_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hephkit.lab.data import snapshots

    source, remote = tmp_path / "src", tmp_path / "remote"
    manifest = build(source)
    snapshots.push(manifest, root=source, remote=str(remote))

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("not a DVC failure")

    monkeypatch.setattr("dvc.repo.Repo.pull", boom)
    with pytest.raises(RuntimeError, match="not a DVC failure"):
        snapshots.pull(manifest, into=tmp_path / "dst", remote=str(remote))


@pytest.mark.extras
def test_a_snapshot_pointer_that_is_not_a_dvc_directory_id_is_refused(tmp_path: Path) -> None:
    from hephkit.lab.data.manifest import data_hash
    from hephkit.lab.data.snapshots import pull, push

    source, remote = tmp_path / "src", tmp_path / "remote"
    manifest = build(source)
    push(manifest, root=source, remote=str(remote))
    pointer = remote / "snapshots" / f"{data_hash(manifest).split(':', 1)[-1]}.json"
    assert pointer.is_file()
    for hostile in ('{"md5": "../../etc/passwd"}', '{"md5": 7}', "not json", "{}"):
        pointer.write_text(hostile)
        with refused():
            pull(manifest, into=tmp_path / "dst", remote=str(remote))


@pytest.mark.extras
def test_pull_leaves_nothing_behind_when_it_refuses(tmp_path: Path) -> None:
    from hephkit.lab.data.snapshots import pull, push

    source, remote, target = tmp_path / "src", tmp_path / "remote", tmp_path / "dst"
    manifest = build(source)
    push(manifest, root=source, remote=str(remote))
    corrupt(remote, FILES["raw/b.csv"], b"id,l\n1,y\n")
    with refused():
        pull(manifest, into=target, remote=str(remote))
    # a.csv arrived intact, and still is not in the destination: all or nothing.
    assert not target.exists() or listing(target) == {}


@pytest.mark.extras
def test_a_refused_pull_does_not_touch_what_the_destination_held(tmp_path: Path) -> None:
    from hephkit.lab.data.snapshots import pull, push

    source, remote, target = tmp_path / "src", tmp_path / "remote", tmp_path / "dst"
    manifest = build(source)
    push(manifest, root=source, remote=str(remote))
    target.mkdir()
    (target / "a.csv").write_bytes(b"previous\n")
    corrupt(remote, FILES["a.csv"], b"id,v\n1,11\n2,20\n")
    with refused():
        pull(manifest, into=target, remote=str(remote))
    assert listing(target) == {"a.csv": b"previous\n"}


@pytest.mark.extras
def test_pulling_a_snapshot_the_remote_never_received_is_missing_not_corrupt(
    tmp_path: Path,
) -> None:
    from hephkit.lab.data.snapshots import pull, push

    source, remote = tmp_path / "src", tmp_path / "remote"
    push(build(source), root=source, remote=str(remote))
    other = build(tmp_path / "other", {"z.csv": b"z\n"})
    with pytest.raises(MissingManifestError) as caught:
        pull(other, into=tmp_path / "dst", remote=str(remote))
    assert caught.value.code == LAB_424


@pytest.mark.extras
def test_pull_refuses_a_destination_directory_a_symlink_routes_outside_the_root(
    tmp_path: Path,
) -> None:
    from hephkit.lab.data.snapshots import pull, push

    source, remote = tmp_path / "src", tmp_path / "remote"
    push(build(source), root=source, remote=str(remote))
    target, elsewhere = tmp_path / "dst", tmp_path / "elsewhere"
    target.mkdir()
    elsewhere.mkdir()
    (target / "raw").symlink_to(elsewhere, target_is_directory=True)
    with refused(match="outside"):
        pull(build(source), into=target, remote=str(remote))
    assert list(elsewhere.iterdir()) == []
    assert not (target / "a.csv").exists()  # refused before any file was written


@pytest.mark.extras
def test_pull_refuses_a_destination_file_that_is_a_symlink_out_of_the_root(tmp_path: Path) -> None:
    from hephkit.lab.data.snapshots import pull, push

    source, remote = tmp_path / "src", tmp_path / "remote"
    manifest = build(source)
    push(manifest, root=source, remote=str(remote))
    target, outside = tmp_path / "dst", tmp_path / "outside.csv"
    target.mkdir()
    outside.write_bytes(b"precious\n")
    (target / "a.csv").symlink_to(outside)
    with refused(match="outside"):
        pull(manifest, into=target, remote=str(remote))
    assert outside.read_bytes() == b"precious\n"


@pytest.mark.extras
def test_a_destination_reached_through_a_symlink_is_not_an_escape(tmp_path: Path) -> None:
    """The root itself being a symlink is the caller's choice; only paths *below* it must stay in."""
    from hephkit.lab.data.snapshots import pull, push

    source, remote, real = tmp_path / "src", tmp_path / "remote", tmp_path / "real"
    manifest = build(source)
    push(manifest, root=source, remote=str(remote))
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    pull(manifest, into=link, remote=str(remote))
    assert listing(real) == FILES
