"""Contract tests for ``hephkit.lab.sources``.

Every cache claim here is proven by counting the fetcher's calls: a test that
only compares returned bodies cannot tell a cache from a passthrough.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hephkit.errors import LAB_412, LAB_424
from hephkit.lab.sources import CorruptSourceError, Request, SourceCache, SourceError, cache_key


class Fetcher:
    """A fake transport that counts how often the network would have been reached."""

    def __init__(self, body: bytes = b"payload") -> None:
        self.body = body
        self.calls: list[Request] = []

    def __call__(self, request: Request) -> bytes:
        self.calls.append(request)
        return self.body


REQ = Request(method="GET", url="https://example.org/data.csv", body=None)


def _only(directory: Path, suffix: str) -> Path:
    (found,) = [p for p in directory.iterdir() if p.suffix == suffix]
    return found


def test_a_fetch_is_frozen_and_the_second_call_does_not_reach_the_fetcher(tmp_path: Path) -> None:
    fetcher = Fetcher()
    cache = SourceCache(tmp_path, upstream_version="v1")
    assert cache.fetch(REQ, fetcher) == b"payload"
    assert cache.fetch(REQ, fetcher) == b"payload"
    assert len(fetcher.calls) == 1


def test_a_cache_written_by_one_object_is_found_by_another(tmp_path: Path) -> None:
    SourceCache(tmp_path, upstream_version="v1").fetch(REQ, Fetcher())
    fetcher = Fetcher(b"different")
    assert SourceCache(tmp_path, upstream_version="v1").fetch(REQ, fetcher) == b"payload"
    assert fetcher.calls == []


def test_a_changed_upstream_version_misses_the_cache(tmp_path: Path) -> None:
    fetcher = Fetcher(b"old")
    SourceCache(tmp_path, upstream_version="v1").fetch(REQ, fetcher)
    fetcher.body = b"new"
    got = SourceCache(tmp_path, upstream_version="v2").fetch(REQ, fetcher)
    assert got == b"new"
    assert len(fetcher.calls) == 2
    # and the old version is still what v1 replays
    assert SourceCache(tmp_path, upstream_version="v1", offline=True).fetch(REQ, fetcher) == b"old"


def test_offline_mode_serves_a_hit(tmp_path: Path) -> None:
    SourceCache(tmp_path, upstream_version="v1").fetch(REQ, Fetcher())
    fetcher = Fetcher()
    cache = SourceCache(tmp_path, upstream_version="v1", offline=True)
    assert cache.fetch(REQ, fetcher) == b"payload"
    assert fetcher.calls == []


def test_offline_mode_refuses_a_miss_rather_than_fetching(tmp_path: Path) -> None:
    fetcher = Fetcher()
    cache = SourceCache(tmp_path, upstream_version="v1", offline=True)
    with pytest.raises(SourceError) as info:
        cache.fetch(REQ, fetcher)
    assert info.value.code == LAB_424
    assert isinstance(info.value, LookupError)
    assert fetcher.calls == []
    assert cache.frozen() == ()


def test_a_body_distinguishes_two_posts_to_one_url(tmp_path: Path) -> None:
    a = Request(method="POST", url="https://x/q", body=b"a")
    b = Request(method="POST", url="https://x/q", body=b"b")
    assert cache_key(a, upstream_version="v") != cache_key(b, upstream_version="v")
    fetcher = Fetcher()
    cache = SourceCache(tmp_path, upstream_version="v")
    cache.fetch(a, fetcher)
    cache.fetch(b, fetcher)
    assert len(fetcher.calls) == 2


def test_method_url_and_body_each_change_the_key_and_none_is_not_empty() -> None:
    base = Request(method="GET", url="https://x/q", body=None)
    keys = {
        cache_key(base, upstream_version="v"),
        cache_key(base.model_copy(update={"method": "POST"}), upstream_version="v"),
        cache_key(base.model_copy(update={"url": "https://x/r"}), upstream_version="v"),
        cache_key(base.model_copy(update={"body": b""}), upstream_version="v"),
    }
    assert len(keys) == 4


def test_the_key_is_stable_across_processes() -> None:
    # Pinned literal, derived by hand: sha256 of the JCS text
    # {"body":null,"method":"GET","upstream_version":"v1","url":"https://example.org/data.csv"}
    # computed with shasum, not our code. A keying change would orphan every cache written before it.
    assert cache_key(REQ, upstream_version="v1") == (
        "sha256:4280cc8e580f410a79353ecf176c4013ea08de3177703c5e4e26314bdcf80fb8"
    )


def test_a_corrupted_frozen_body_is_refused_rather_than_served(tmp_path: Path) -> None:
    SourceCache(tmp_path, upstream_version="v1").fetch(REQ, Fetcher())
    _only(tmp_path, ".body").write_bytes(b"tampered")
    fetcher = Fetcher()
    for offline in (False, True):
        with pytest.raises(CorruptSourceError) as info:
            SourceCache(tmp_path, upstream_version="v1", offline=offline).fetch(REQ, fetcher)
        assert info.value.code == LAB_412
    assert fetcher.calls == []


def test_a_sidecar_without_its_body_is_a_miss(tmp_path: Path) -> None:
    SourceCache(tmp_path, upstream_version="v1").fetch(REQ, Fetcher())
    _only(tmp_path, ".body").unlink()
    with pytest.raises(SourceError):
        SourceCache(tmp_path, upstream_version="v1", offline=True).fetch(REQ, Fetcher())


def test_frozen_reports_what_is_on_disk_for_this_version(tmp_path: Path) -> None:
    cache = SourceCache(tmp_path, upstream_version="v1")
    assert cache.frozen() == ()
    other = Request(method="GET", url="https://x/other", body=None)
    cache.fetch(REQ, Fetcher())
    cache.fetch(other, Fetcher())
    SourceCache(tmp_path, upstream_version="v2").fetch(REQ, Fetcher())
    expected = tuple(sorted(cache_key(r, upstream_version="v1") for r in (REQ, other)))
    assert cache.frozen() == expected
    # removing a file is noticed: the object remembers nothing
    (tmp_path / (expected[0].split(":")[1] + ".body")).unlink()
    assert cache.frozen() == expected[1:]


def test_the_sidecar_is_readable_and_names_the_request(tmp_path: Path) -> None:
    SourceCache(tmp_path, upstream_version="v1").fetch(REQ, Fetcher())
    doc = json.loads(_only(tmp_path, ".json").read_text())
    assert doc["request"]["url"] == REQ.url
    assert doc["upstream_version"] == "v1"
    assert len(doc["sha256"]) == 64


def test_a_failing_fetcher_freezes_nothing(tmp_path: Path) -> None:
    def boom(request: Request) -> bytes:
        raise ConnectionError("down")

    cache = SourceCache(tmp_path, upstream_version="v1")
    with pytest.raises(ConnectionError):
        cache.fetch(REQ, boom)
    assert cache.frozen() == ()


def test_a_fetcher_must_return_bytes(tmp_path: Path) -> None:
    cache = SourceCache(tmp_path, upstream_version="v1")
    with pytest.raises(TypeError):
        cache.fetch(REQ, lambda r: "text")  # type: ignore[arg-type,return-value]
    assert cache.frozen() == ()


def test_an_unreadable_sidecar_is_corrupt_not_a_miss(tmp_path: Path) -> None:
    SourceCache(tmp_path, upstream_version="v1").fetch(REQ, Fetcher())
    _only(tmp_path, ".json").write_text("{not json")
    with pytest.raises(CorruptSourceError):
        SourceCache(tmp_path, upstream_version="v1", offline=True).fetch(REQ, Fetcher())


def test_frozen_skips_records_it_cannot_read_and_stray_files(tmp_path: Path) -> None:
    SourceCache(tmp_path, upstream_version="v1").fetch(REQ, Fetcher())
    (tmp_path / "junk.json").write_text("{not json")
    (tmp_path / "junk.body").write_bytes(b"x")
    (tmp_path / "list.json").write_text("[]")
    (tmp_path / "list.body").write_bytes(b"x")
    (tmp_path / "orphan.json").write_text("{}")
    assert SourceCache(tmp_path, upstream_version="v1").frozen() == (
        cache_key(REQ, upstream_version="v1"),
    )


def test_a_failed_write_leaves_no_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("hephkit.lab.sources.os.replace", refuse)
    with pytest.raises(OSError):
        SourceCache(tmp_path, upstream_version="v1").fetch(REQ, Fetcher())
    assert list(tmp_path.iterdir()) == []


def test_a_sidecar_with_no_digest_is_corrupt(tmp_path: Path) -> None:
    SourceCache(tmp_path, upstream_version="v1").fetch(REQ, Fetcher())
    _only(tmp_path, ".json").write_text("[]")
    with pytest.raises(CorruptSourceError):
        SourceCache(tmp_path, upstream_version="v1", offline=True).fetch(REQ, Fetcher())
