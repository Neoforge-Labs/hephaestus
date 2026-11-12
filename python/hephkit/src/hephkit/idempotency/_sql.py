"""SQL for the idempotency record store (spec 2.3).

``DDL`` is read from ``schema.sql`` rather than repeated here, so the file and
the constant cannot drift. It is idempotent (``IF NOT EXISTS``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

__all__ = ["DDL"]

DDL: Final = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
