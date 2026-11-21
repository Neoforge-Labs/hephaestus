"""The import guard for the optional extras of ``hephkit-lab``.

The spine installs with no scientific stack (ADR 0023), so a module that needs
one -- pandas, polars, DVC -- imports it lazily through :func:`require`, which
turns a bare ``ModuleNotFoundError`` into one that names the extra to install.
Nothing else lives here.

Maturity: experimental.
"""

from __future__ import annotations

import importlib
from types import ModuleType

__all__ = ["MissingExtraError", "require"]


class MissingExtraError(ImportError):
    """An optional dependency is not installed; the message names the extra."""


def require(module: str, *, extra: str) -> ModuleType:
    """Import ``module``, or raise :class:`MissingExtraError` naming ``extra``.

    Only the *absence* of ``module`` (or of one of its parent packages) is
    translated. A module that is installed but fails on an import of its own is
    a different fault, and reporting it as "install the extra" would send the
    caller to fix the wrong thing, so that ``ModuleNotFoundError`` propagates.
    """
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if module != missing and not module.startswith(missing + "."):
            raise
        raise MissingExtraError(
            f"{module!r} is not installed; install it with: pip install 'hephkit-lab[{extra}]'"
        ) from exc
