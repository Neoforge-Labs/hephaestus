"""``hephkit`` is a PEP 420 namespace package (ADR 0021).

The distribution owns no ``hephkit/__init__.py``, so a second distribution
(``hephkit-lab``) can install ``hephkit/lab/`` into the same namespace. The
version is read from installed metadata, not from an attribute on the package.
"""

from __future__ import annotations

from pathlib import Path


def test_hephkit_is_a_namespace_package() -> None:
    import hephkit

    assert not hasattr(hephkit, "__file__") or hephkit.__file__ is None


def test_version_is_available_from_metadata() -> None:
    """The version is reachable from installed metadata, whatever it happens to be.

    Deliberately not pinned to a literal: what must not regress is that the
    version is *reachable*, now that there is no ``hephkit.__version__`` to read.
    Pinning ``0.3`` here would make this test fail on the next bump, which would
    say nothing about the namespace package.
    """
    import re
    import tomllib
    from importlib.metadata import version

    installed = version("hephkit")
    assert installed, "metadata reports no version for hephkit"
    # PEP 440 release segment: at least `N.N`, so a truncated or empty value fails.
    assert re.match(r"^\d+\.\d+", installed), f"not a version: {installed!r}"

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert installed == declared, (
        f"metadata says {installed!r} but pyproject.toml declares {declared!r}; "
        "reinstall with `uv run maturin develop --uv`"
    )


def test_submodules_still_import() -> None:
    from hephkit.hashing import content_hash
    from hephkit.money import Money

    assert content_hash({"a": 1}).startswith("sha256:")
    assert Money.parse("1.00", "USD").minor == 100
