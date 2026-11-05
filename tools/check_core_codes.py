# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Check that every error code the compiled core exposes is in spec/errors.yaml.

CLAUDE.md says codes live only in the registry, but the Rust core carries them
as literals. This closes the loop cheaply from the Python side, without parsing
Rust. It SAMPLES codes; it does not cover every code the core holds. It collects
(1) every string attribute of ``hephkit._core`` that looks like a code or is named
``*_CODE``, and (2) the ``.code`` of the exception raised by a few probe calls that
fail on purpose (HEPH-MONEY-422, HEPH-MONEY-409, HEPH-WH-401, HEPH-VAL-422), and
reports any that the registry lacks. A code no probe reaches is not checked: add
a probe when the core gains a new failure path.

Needs the built extension, so run it inside the hephkit environment:
``cd python/hephkit && uv run --with pyyaml ../../tools/check_core_codes.py``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml
from check_registry import CODE_RE, check_errors


def _probes(core: Any) -> list[Callable[[], object]]:
    """Calls that must fail inside the core, one per exception class."""
    return [
        lambda: core.money_check(0, "ZZZ"),
        lambda: core.money_add(1, "USD", 1, "EUR"),
        lambda: core.verify("whsec_dGVzdA==", "", "", "", b"", 0, 300),
        lambda: core.content_hash_json("{"),
        lambda: core.sign("", "id", 0, b""),
    ]


def check_core_codes(
    registry: Path,
    core: ModuleType | Any,
    probes: Sequence[Callable[[], object]] | None = None,
) -> list[str]:
    """Return findings for codes exposed by ``core`` that the registry lacks."""
    findings = check_errors(registry)
    if findings:
        return findings
    known = {entry["code"] for entry in yaml.safe_load(registry.read_text(encoding="utf-8"))}

    for name in sorted(vars(core)):
        value = getattr(core, name)
        if not isinstance(value, str):
            continue
        if name.endswith("_CODE") or value.startswith("HEPH-"):
            if not CODE_RE.fullmatch(value):
                findings.append(f"_core.{name}: {value!r} is not a well-formed error code")
            elif value not in known:
                findings.append(f"_core.{name}: {value} is not in spec/errors.yaml")

    for probe in _probes(core) if probes is None else probes:
        try:
            probe()
        except Exception as exc:  # noqa: BLE001 - we want whatever the core raised
            code = getattr(exc, "code", None)
            if code is None:
                findings.append(f"probe raised {type(exc).__name__} without a .code")
            elif code not in known:
                findings.append(f"probe raised code {code} which is not in spec/errors.yaml")
        else:
            findings.append("probe did not raise; the check no longer exercises this path")
    return findings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        from hephkit import _core
    except ImportError as exc:
        print(f"cannot import hephkit._core ({exc}); build it with maturin first", file=sys.stderr)
        return 1
    findings = check_core_codes(root / "spec" / "errors.yaml", _core)
    for finding in findings:
        print(finding, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
