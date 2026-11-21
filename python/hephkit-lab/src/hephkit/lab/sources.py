"""Frozen external inputs: a response is stored under a version-pinned key and replayed offline.

:mod:`hephkit.lab.data` identifies a dataset you already hold. This module is
about an input that came off the network and must still be there, byte for
byte, when the run is replayed a year later.

The freezing mechanism is a content-addressed cache at the ``fetch`` boundary,
not transport interception (vcrpy and the like). The lesson worth keeping is the
**version-pinned key**: :func:`cache_key` hashes the request *and* the upstream
version, so a hit whose upstream algorithm or release has moved is a miss and is
never served stale. Interception would also patch ``httplib`` process-wide and
collide with the in-process network block the integrity gates prove. The caller
owns the transport: :meth:`SourceCache.fetch` takes the callable that reaches
the network, and this module never does.

The key is ``content_hash`` (RFC 8785 JCS + SHA-256, spec 4.2) of
``{"method", "url", "body", "upstream_version"}``, where ``body`` is the
standard base64 of the request body or JSON ``null``. ``None`` and ``b""`` are
therefore different requests. The body digest recorded beside each response is a
plain SHA-256: an integrity check, not a second keying scheme.

Layout: ``<hex>.body`` holds the response and ``<hex>.json`` a readable sidecar
(key, request, upstream version, body SHA-256). The body is written first and
the sidecar last, each through a temp file and ``os.replace``, so a sidecar
never names a body that is not there. The disk is consulted on every call, so
:meth:`SourceCache.frozen` reports what is on disk, not what the object remembers.

Which error means what: an input that is not frozen, in a run that may not
reach the network (``offline=True``), is :class:`SourceError` (``HEPH-LAB-424``,
a frozen input is missing). A frozen body whose bytes no longer match the digest
recorded when it was frozen, or a sidecar that cannot be read, exists but says
the wrong thing: :class:`CorruptSourceError` (``HEPH-LAB-412``). It is refused
online too and is not repaired by fetching again, because a silent refetch would
hide the very change replay exists to find.

Limits: the cache trusts its directory only as far as the recorded digest
reaches; someone who rewrites body and sidecar together is not detected. The
fetcher's exceptions propagate unchanged and freeze nothing. Entries are never
evicted, and concurrent writers of one key are not locked (same key, same
bytes, atomic replace, so the race is benign for a deterministic source).

Maturity: experimental.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from hephkit.errors import LAB_412, LAB_424
from hephkit.hashing import content_hash

__all__ = ["CorruptSourceError", "Request", "SourceCache", "SourceError", "cache_key"]


class SourceError(LookupError):
    """A frozen input is not in the cache and the run may not fetch it (``HEPH-LAB-424``)."""

    code = LAB_424


class CorruptSourceError(ValueError):
    """A frozen input exists but no longer matches what was recorded (``HEPH-LAB-412``)."""

    code = LAB_412


class Request(BaseModel):
    """One request to an external source. ``body=None`` and ``body=b""`` are different."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: str
    url: str
    body: bytes | None


def _encoded_body(request: Request) -> str | None:
    return None if request.body is None else base64.b64encode(request.body).decode("ascii")


def cache_key(request: Request, *, upstream_version: str) -> str:
    """``sha256:`` content hash of the request and the upstream version it was made against."""
    return content_hash(
        {
            "method": request.method,
            "url": request.url,
            "body": _encoded_body(request),
            "upstream_version": upstream_version,
        }
    )


def _atomic_write(path: Path, data: bytes) -> None:
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=".hephkit-source-")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _read_sidecar(sidecar: Path) -> dict[str, Any]:
    try:
        doc = json.loads(sidecar.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CorruptSourceError(f"frozen-input record {sidecar.name} is unreadable: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("sha256"), str):
        raise CorruptSourceError(f"frozen-input record {sidecar.name} has no body digest")
    return doc


class SourceCache:
    """A directory of frozen responses for one upstream version."""

    def __init__(self, directory: Path, *, upstream_version: str, offline: bool = False) -> None:
        self._dir = Path(directory)
        self._version = upstream_version
        self._offline = offline

    def _paths(self, key: str) -> tuple[Path, Path]:
        stem = key.split(":", 1)[-1]
        return self._dir / f"{stem}.body", self._dir / f"{stem}.json"

    def _lookup(self, key: str) -> bytes | None:
        """The frozen body for ``key``, ``None`` if it is not frozen, or refuse if it is corrupt."""
        body_path, sidecar = self._paths(key)
        if not sidecar.is_file():
            return None
        try:
            body = body_path.read_bytes()
        except FileNotFoundError:
            return None
        doc = _read_sidecar(sidecar)
        if hashlib.sha256(body).hexdigest() != doc["sha256"]:
            raise CorruptSourceError(
                f"frozen body {body_path.name} no longer matches the digest recorded when it was frozen"
            )
        return body

    def fetch(self, request: Request, fetcher: Callable[[Request], bytes]) -> bytes:
        """The frozen response to ``request``, fetching and freezing it on a miss.

        Offline, a miss raises :class:`SourceError` and ``fetcher`` is not called.
        """
        key = cache_key(request, upstream_version=self._version)
        frozen = self._lookup(key)
        if frozen is not None:
            return frozen
        if self._offline:
            raise SourceError(
                f"{request.method} {request.url} is not frozen for upstream version "
                f"{self._version!r} and this run may not fetch it"
            )
        body = fetcher(request)
        if not isinstance(body, bytes):
            raise TypeError(f"fetcher must return bytes, not {type(body).__name__}")
        self._dir.mkdir(parents=True, exist_ok=True)
        body_path, sidecar = self._paths(key)
        record = {
            "key": key,
            "request": {
                "method": request.method,
                "url": request.url,
                "body": _encoded_body(request),
            },
            "upstream_version": self._version,
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        _atomic_write(body_path, body)
        _atomic_write(sidecar, json.dumps(record, sort_keys=True, indent=2).encode("utf-8"))
        return body

    def frozen(self) -> tuple[str, ...]:
        """Sorted keys of the entries on disk for this upstream version, body and record both present."""
        if not self._dir.is_dir():
            return ()
        keys: list[str] = []
        for sidecar in self._dir.glob("*.json"):
            if not sidecar.with_suffix(".body").is_file():
                continue
            try:
                doc = json.loads(sidecar.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(doc, dict) and doc.get("upstream_version") == self._version:
                key = doc.get("key")
                if isinstance(key, str):
                    keys.append(key)
        return tuple(sorted(keys))
