"""The optional-extra import guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from hephkit.lab.extras import MissingExtraError, require


def test_require_returns_an_importable_module() -> None:
    import json

    assert require("json", extra="data") is json


def test_require_names_the_extra_to_install_when_the_module_is_absent() -> None:
    with pytest.raises(MissingExtraError) as exc:
        require("hephkit_surely_not_installed", extra="data")
    message = str(exc.value)
    assert "hephkit_surely_not_installed" in message
    assert "hephkit-lab[data]" in message
    assert isinstance(exc.value, ImportError)


def test_a_module_that_fails_inside_its_own_import_is_not_reported_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "hephkit_broken_mod.py"
    broken.write_text("import hephkit_surely_not_installed_dep\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ModuleNotFoundError) as exc:
        require("hephkit_broken_mod", extra="data")
    assert not isinstance(exc.value, MissingExtraError)
