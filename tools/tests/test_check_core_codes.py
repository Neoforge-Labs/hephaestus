"""Tests for tools/check_core_codes.py."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_core_codes import check_core_codes, main  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ERRORS = REPO_ROOT / "spec" / "errors.yaml"


def _core(**attrs: object) -> SimpleNamespace:
    return SimpleNamespace(**attrs)


def test_known_codes_pass() -> None:
    core = _core(MONEY_INVALID_CODE="HEPH-MONEY-422", DEFAULT_TOLERANCE_SECS=300)
    assert check_core_codes(ERRORS, core, probes=[]) == []


def test_unknown_constant_is_reported() -> None:
    core = _core(MONEY_INVALID_CODE="HEPH-MONEY-999")
    errors = check_core_codes(ERRORS, core, probes=[])
    assert len(errors) == 1 and "HEPH-MONEY-999" in errors[0]


def test_malformed_code_constant_is_reported() -> None:
    errors = check_core_codes(ERRORS, _core(SOME_CODE="not-a-code"), probes=[])
    assert len(errors) == 1 and "SOME_CODE" in errors[0]


def test_probe_raising_unknown_code_is_reported() -> None:
    def boom() -> None:
        err = ValueError("x")
        err.code = "HEPH-ZZ-123"  # type: ignore[attr-defined]
        raise err

    errors = check_core_codes(ERRORS, _core(), probes=[boom])
    assert len(errors) == 1 and "HEPH-ZZ-123" in errors[0]


def test_probe_raising_known_code_passes() -> None:
    def ok() -> None:
        err = ValueError("x")
        err.code = "HEPH-WH-401"  # type: ignore[attr-defined]
        raise err

    assert check_core_codes(ERRORS, _core(), probes=[ok]) == []


def test_probe_that_does_not_raise_is_reported() -> None:
    errors = check_core_codes(ERRORS, _core(), probes=[lambda: None])
    assert len(errors) == 1 and "did not raise" in errors[0]


def test_missing_registry_is_reported(tmp_path: Path) -> None:
    errors = check_core_codes(tmp_path / "nope.yaml", _core(), probes=[])
    assert errors and "does not exist" in errors[0]


def test_real_core_is_consistent() -> None:
    import pytest

    pytest.importorskip(
        "hephkit._core",
        reason="expected to run under the hephkit moon task `core-codes`, "
        "which has the built extension; skipped in a bare tools environment",
    )
    from check_core_codes import _probes

    reached = set()
    for probe in _probes(hephkit_core := __import__("hephkit._core", fromlist=["_core"])):
        try:
            probe()
        except Exception as exc:  # noqa: BLE001
            reached.add(getattr(exc, "code", None))
    assert hephkit_core is not None
    assert {"HEPH-MONEY-422", "HEPH-MONEY-409", "HEPH-WH-401", "HEPH-VAL-422"} <= reached
    assert main() == 0
