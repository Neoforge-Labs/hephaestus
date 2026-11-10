"""Registry-backed errors (spec section 1). Maturity: experimental.

``HephError`` is an exception that carries a code from ``spec/errors.yaml``. The
code constants and the ``REGISTRY`` of ``(status, title)`` are generated into
``_codes.py``. This module does not import FastAPI; the web layer lives in
``hephkit.errors.fastapi``.
"""

from typing import Any

from hephkit.errors import _codes
from hephkit.errors._codes import *  # noqa: F403 - the generated code constants
from hephkit.errors._codes import DETAIL_HINTS, REGISTRY

__all__ = ["DETAIL_HINTS", "REGISTRY", "TYPE_BASE_URL", "HephError", *[n for n in dir(_codes) if n[:1].isupper() and n != "Final"]]

TYPE_BASE_URL = "https://hephkit.dev/errors/"

# Members of the problem+json body that an extension may not overwrite.
RESERVED_MEMBERS = frozenset({"type", "title", "status", "detail", "code", "trace_id"})


class HephError(Exception):
    """An error with a registry code. ``status``, ``title`` and ``type_url`` come
    from the registry; ``detail`` (for the caller, spec 1.7) and any extra
    ``extensions`` are carried into the response body.

    An unregistered ``code`` raises ``ValueError`` at construction, as does an
    extension named like a reserved problem member.
    """

    def __init__(self, code: str, detail: str | None = None, **extensions: Any) -> None:
        if not isinstance(code, str) or code not in REGISTRY:
            raise ValueError(f"unknown error code {code!r}: codes must be in spec/errors.yaml")
        clash = sorted(RESERVED_MEMBERS.intersection(extensions))
        if clash:
            raise ValueError(f"extension names are reserved by problem+json: {', '.join(clash)}")
        super().__init__(detail or REGISTRY[code][1])
        self._code = code
        self.detail = detail
        self.extensions = extensions

    @property
    def code(self) -> str:
        return self._code

    @property
    def status(self) -> int:
        return REGISTRY[self._code][0]

    @property
    def title(self) -> str:
        return REGISTRY[self._code][1]

    @property
    def type_url(self) -> str:
        return TYPE_BASE_URL + self._code
