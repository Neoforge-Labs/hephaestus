"""``hephkit`` is a PEP 420 namespace package (ADR 0024).

The distribution owns no ``hephkit/__init__.py``, so a second distribution
(``hephkit-lab``) can install ``hephkit/lab/`` into the same namespace. The
version is read from installed metadata, not from an attribute on the package.
"""

from __future__ import annotations


def test_hephkit_is_a_namespace_package() -> None:
    import hephkit

    assert not hasattr(hephkit, "__file__") or hephkit.__file__ is None


def test_version_is_available_from_metadata() -> None:
    from importlib.metadata import version

    assert version("hephkit").startswith("0.3")


def test_submodules_still_import() -> None:
    from hephkit.hashing import content_hash
    from hephkit.money import Money

    assert content_hash({"a": 1}).startswith("sha256:")
    assert Money.parse("1.00", "USD").minor == 100
