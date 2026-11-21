"""DVC snapshots of a manifest's files, over a local directory remote.

A directory remote needs no daemon, credentials or S3, and what is under test
(a snapshot round-trips; a corrupted arrival is refused) does not depend on the
object-store protocol. The refusal tests corrupt what is *in the remote*, not
the happy path, because `pull` is the one function here that handles bytes it
did not write.
"""

from __future__ import annotations

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
    with pytest.raises(ManifestError, match="a.csv"):
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
    with pytest.raises(ManifestError) as caught:
        pull(manifest, into=target, remote=str(remote))
    assert caught.value.code == LAB_412
    assert not target.exists() or listing(target) == {}


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
        with pytest.raises(ManifestError):
            pull(manifest, into=tmp_path / "dst", remote=str(remote))


@pytest.mark.extras
def test_pull_leaves_nothing_behind_when_it_refuses(tmp_path: Path) -> None:
    from hephkit.lab.data.snapshots import pull, push

    source, remote, target = tmp_path / "src", tmp_path / "remote", tmp_path / "dst"
    manifest = build(source)
    push(manifest, root=source, remote=str(remote))
    corrupt(remote, FILES["raw/b.csv"], b"id,l\n1,y\n")
    with pytest.raises(ManifestError):
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
    with pytest.raises(ManifestError):
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
    with pytest.raises(ManifestError, match="outside"):
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
    with pytest.raises(ManifestError, match="outside"):
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
