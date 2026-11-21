"""DVC snapshots of a dataset: push the files a manifest names, pull them back and distrust them.

A snapshot is the manifest's files stored in a DVC remote under the manifest's
``data_hash`` (spec 10.2), which is the only name a reader needs: a provenance
record names the hash, and :func:`pull` fetches the bytes that hash describes.

DVC is driven through its Python API, in a throwaway repository under a
temporary directory, so neither the caller's dataset directory nor the
destination ever becomes a DVC repository. DVC's own object ids are MD5; they
locate objects and nothing else. Whether what arrived is the dataset is decided
by :func:`~hephkit.lab.data.manifest.verify_manifest` against the manifest's
SHA-256 digests, and no digest is derived here.

:func:`pull` is the one function in this package that handles bytes it did not
write, so it distrusts them twice: everything is fetched into a scratch
directory and verified there, and only then copied into ``into``, so a **refused**
pull leaves ``into`` as it found it -- every refusal this module makes happens
before the first byte is written there. A **failed copy** is a weaker promise:
the copies run one destination at a time, each atomic in itself, so an I/O
error partway through leaves the destinations already copied in place and the
rest absent. Nothing half-written, but not all-or-nothing either; a caller that
needs that must pull into a directory it can discard. Each destination path is
resolved first and refused if it leaves ``into``: ``verify_manifest`` checks a
path lexically (spec 10.1 forbids ``.`` and ``..``), which a symlink inside
``into`` defeats.

DVC lives behind the ``data`` extra (ADR 0023) and is imported inside the
functions that need it, through :func:`~hephkit.lab._extras.require`, so a
spine-only install can import this module.

Which error means what: a file that arrived and disagrees with the manifest is
``ManifestError`` (``HEPH-LAB-412``, the integrity gate found what it exists to
find). A snapshot that could not be obtained at all -- no pointer, an
unreachable remote, an object DVC cannot fetch -- is ``MissingManifestError``
(``HEPH-LAB-424``, the dependency is absent, not corrupt). Only DVC's own
exception family is translated; anything else propagates unchanged.

Coupling to DVC: the snapshot pointer is stored beside DVC's object tree, at
``<remote root>/snapshots/``, and the remote root is derived from the object
store path DVC reports, which in DVC 3.x ends in ``files/md5``. A DVC release
that moves that layout breaks :func:`push` and :func:`pull` at
``_pointer_path``, which raises :class:`UnsupportedDvcLayoutError` naming the
DVC version it found and the one the layout belongs to, rather than failing
later with an unrelated lookup error. The pointer's md5 ids and the generated
``.dvc`` text (``hash: md5``) are likewise DVC 3.x conventions.

A snapshot is one directory of copies, so ``push`` needs room for the files it
sends. Verification is not atomic with the copy out of scratch: a process that
rewrites the scratch directory mid-pull is outside what this guards.

The destination-escape check is not atomic with the write either: ``pull``
resolves every destination, then writes, so a process that swaps a symlink into
``into`` in between defeats it. Closing that needs ``dir_fd``/``O_NOFOLLOW``
writes and is out of scope. The realistic hazard is covered: what comes off the
remote cannot create a link inside ``into`` (only manifest-named regular files
are copied, and a link in the arrival is refused), so a link there is one the
caller or another process already placed.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

from hephkit.lab._extras import require
from hephkit.lab.data.manifest import (
    Manifest,
    ManifestError,
    MissingManifestError,
    data_hash,
    verify_manifest,
)

__all__ = ["UnsupportedDvcLayoutError", "pull", "push"]

_LAYOUT_DVC = "3.x"


class UnsupportedDvcLayoutError(RuntimeError):
    """The installed DVC lays out its remote differently from the layout this module relies on."""


_REMOTE = "snapshot"
_DATA = "data"
_POINTER_DIR = "snapshots"
_DIR_ID = re.compile(r"[0-9a-f]{32}\.dir")


def _remote_url(remote: str) -> str:
    """``remote`` as DVC should read it: a local path is made absolute, a URL is left alone."""
    return remote if "://" in remote else str(Path(remote).resolve())


@contextmanager
def _scratch_repo(remote: str) -> Iterator[tuple[Any, Path]]:
    """A throwaway DVC repository pointed at ``remote``, and the directory it lives in."""
    dvc_repo = require("dvc.repo", extra="data")
    with tempfile.TemporaryDirectory(prefix="hephkit-snapshot-") as scratch:
        work = Path(scratch)
        repo = dvc_repo.Repo.init(str(work), no_scm=True)
        try:
            with repo.config.edit() as config:
                config["core"]["analytics"] = "false"
                config["core"]["remote"] = _REMOTE
                config["cache"] = {"type": "copy"}
                config["remote"][_REMOTE] = {"url": _remote_url(remote)}
            yield repo, work
        finally:
            repo.close()


def _pointer_path(odb: Any, manifest: Manifest) -> str:
    """Where the pointer for ``manifest`` lives: beside DVC's ``files/md5`` tree, named by hash."""
    objects = posixpath.normpath(str(odb.path))
    files_dir = posixpath.dirname(objects)
    if posixpath.basename(objects) != "md5" or posixpath.basename(files_dir) != "files":
        installed = getattr(require("dvc", extra="data"), "__version__", "unknown")
        raise UnsupportedDvcLayoutError(
            f"DVC {installed} reports its object store at {odb.path!r}, not under "
            f"'<remote>/files/md5' as DVC {_LAYOUT_DVC} lays it out; snapshot pointers "
            "cannot be placed beside it"
        )
    hex_digest = data_hash(manifest).split(":", 1)[-1]
    return posixpath.join(posixpath.dirname(files_dir), _POINTER_DIR, f"{hex_digest}.json")


def push(manifest: Manifest, *, root: Path, remote: str) -> None:
    """Store the files ``manifest`` names, read from ``root``, in the DVC ``remote``.

    ``root`` is verified against the manifest first (``ManifestError`` on a
    disagreement, ``HEPH-LAB-412``), so a snapshot is only ever made of bytes the
    manifest describes. Only the files the manifest lists are sent; anything
    else under ``root`` is not. ``remote`` is a DVC remote URL or a local directory.
    """
    require("dvc", extra="data")
    verify_manifest(manifest, root)
    with _scratch_repo(remote) as (repo, work):
        data = work / _DATA
        for entry in manifest.files:
            target = data / entry.path
            target.parent.mkdir(parents=True, exist_ok=True)
            # A copy, never a link: DVC protects (chmods) what it takes into its
            # cache, and a hardlink would carry that onto the caller's own file.
            shutil.copyfile(root / entry.path, target)
        stages = repo.add(str(data))
        repo.push()
        out = stages[0].outs[0]
        pointer = {"md5": out.hash_info.value, "nfiles": out.meta.nfiles, "size": out.meta.size}
        odb = repo.cloud.get_remote_odb(_REMOTE)
        location = _pointer_path(odb, manifest)
        odb.fs.makedirs(posixpath.dirname(location), exist_ok=True)
        # Written last: a pointer never names objects the remote does not hold.
        odb.fs.pipe_file(location, json.dumps(pointer, sort_keys=True).encode("utf-8"))


def _read_pointer(repo: Any, manifest: Manifest, remote: str, dvc_exceptions: ModuleType) -> str:
    """The DVC directory id of the snapshot of ``manifest``, or refuse (it is not trusted).

    A remote DVC cannot open or read is a snapshot that is absent (424), not one
    that is corrupt.
    """
    try:
        odb = repo.cloud.get_remote_odb(_REMOTE)
        location = _pointer_path(odb, manifest)
    except dvc_exceptions.DvcException as exc:
        raise MissingManifestError(
            f"could not read a snapshot from remote {remote!r}: {exc}"
        ) from exc
    try:
        raw = odb.fs.cat_file(location)
    except FileNotFoundError as exc:
        raise MissingManifestError(
            f"remote {remote!r} holds no snapshot of data_hash {data_hash(manifest)}"
        ) from exc
    except (dvc_exceptions.DvcException, OSError) as exc:
        # A remote that is configured but cannot be reached on the wire
        # (connection refused, timeout, a provider's I/O error) is an
        # unobtainable snapshot, not a corrupt one. Narrow on purpose: this one
        # read, and only DVC's family and OSError. It is its own block because
        # MissingManifestError is a ValueError, and the parse below must not
        # catch and relabel it as 412.
        raise MissingManifestError(
            f"could not read a snapshot from remote {remote!r}: {exc}"
        ) from exc
    try:
        md5 = json.loads(raw)["md5"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ManifestError(f"the remote's snapshot pointer is not valid: {exc}") from exc
    if not isinstance(md5, str) or not _DIR_ID.fullmatch(md5):
        raise ManifestError(f"the remote's snapshot pointer names {md5!r}, not a DVC directory id")
    return md5


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _destinations(manifest: Manifest, into: Path) -> list[tuple[str, Path]]:
    """Each manifest path with its destination, refusing any that resolves outside ``into``.

    Resolution follows symlinks, so a symlinked directory in ``into`` that leads
    elsewhere, or a destination file that is itself a link out, is caught. The
    root is resolved too: ``into`` being reached through a link is the caller's
    choice, and only what lies *below* it must stay below it.
    """
    root = into.resolve()
    out: list[tuple[str, Path]] = []
    for entry in manifest.files:
        destination = root / entry.path
        if not _inside(destination.resolve(), root):
            raise ManifestError(
                f"{entry.path!r} would be written outside {into}: a symlink routes it elsewhere"
            )
        out.append((entry.path, destination))
    return out


def _place(source: Path, destination: Path) -> None:
    """Copy ``source`` to ``destination`` through a sibling temp file, so a path is never half-written."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=destination.parent, prefix=".hephkit-pull-")
    try:
        with os.fdopen(handle, "wb") as out, source.open("rb") as arrived:
            shutil.copyfileobj(arrived, out)
        os.replace(name, destination)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _fetch(repo: Any, work: Path, md5: str, remote: str, dvc_exceptions: ModuleType) -> Path:
    """Check the snapshot ``md5`` out of the remote into ``work`` and return the directory."""
    (work / f"{_DATA}.dvc").write_text(
        # `hash: md5` is what makes DVC 3 look for the id as pushed; without it the
        # id is read as the legacy md5-dos2unix scheme and the object is "missing".
        f"outs:\n- md5: {md5}\n  hash: md5\n  path: {_DATA}\n",
        encoding="utf-8",
    )
    try:
        repo.pull()
    except (dvc_exceptions.DvcException, OSError) as exc:
        # Failing to obtain the snapshot is absence (424), not corruption: a
        # digest disagreement is only ever found by `verify_manifest` (412).
        #
        # `OSError` for the same reason `_read_pointer` catches it, and
        # symmetrically with it: a host that answered the pointer read can die
        # mid-fetch (connection reset, a timeout, a provider's I/O error), and a
        # raw OSError reaching the caller is the uncoded outcome the 412/424
        # split exists to prevent. Narrow on purpose -- this one call, and only
        # DVC's family and OSError.
        raise MissingManifestError(
            f"the snapshot could not be fetched from remote {remote!r}: {exc}"
        ) from exc
    return work / _DATA


def pull(manifest: Manifest, *, into: Path, remote: str) -> None:
    """Fetch the snapshot of ``manifest`` from ``remote`` into ``into``, or refuse.

    What arrives is distrusted. It is fetched into scratch space and checked with
    ``verify_manifest`` there; a file whose bytes disagree with the manifest's
    digests, or that is missing, raises ``ManifestError`` (``HEPH-LAB-412``) and
    ``into`` is left exactly as it was, because every refusal happens before the
    first byte is written there. An I/O error during the copy itself is not a
    refusal and makes no such promise -- the destinations already copied stay.
    A snapshot that cannot be obtained -- the
    remote never received it, is unreachable, or lacks an object -- is
    ``MissingManifestError`` (``HEPH-LAB-424``), never 412. Every destination path is
    resolved before anything is written, and one that leaves ``into`` (a symlink
    inside it points out) is refused with ``ManifestError``. Only files the
    manifest names are written.
    """
    dvc_exceptions = require("dvc.exceptions", extra="data")
    with ExitStack() as stack:
        try:
            repo, work = stack.enter_context(_scratch_repo(remote))
        except dvc_exceptions.DvcException as exc:
            # DVC refuses to configure a remote it does not understand: no
            # snapshot can come from it, which is absence, not corruption.
            raise MissingManifestError(f"remote {remote!r} cannot be used: {exc}") from exc
        md5 = _read_pointer(repo, manifest, remote, dvc_exceptions)
        arrived = _fetch(repo, work, md5, remote, dvc_exceptions)
        # Scratch is ours, but what DVC put in it came from the remote: a link in
        # it must not lead `verify_manifest` or the copy to a file outside it.
        base = arrived.resolve()
        for entry in manifest.files:
            candidate = arrived / entry.path
            if candidate.is_symlink() or not _inside(candidate.resolve(), base):
                raise ManifestError(f"{entry.path!r} arrived as a link, not as a file")
        verify_manifest(manifest, arrived)
        destinations = _destinations(manifest, into)
        for path, destination in destinations:
            _place(arrived / path, destination)
