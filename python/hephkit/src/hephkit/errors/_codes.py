"""Error-code constants generated from spec/errors.yaml.

GENERATED FILE - do not edit by hand. Regenerate with
``uv run tools/gen_errors.py``; CI runs ``--check``. Codes live only in
``spec/errors.yaml``.
"""

from typing import Final

GEN_500: Final = "HEPH-GEN-500"
VAL_422: Final = "HEPH-VAL-422"
NF_404: Final = "HEPH-NF-404"
AUTH_401: Final = "HEPH-AUTH-401"
AUTH_403: Final = "HEPH-AUTH-403"
RATE_429: Final = "HEPH-RATE-429"
IDEMP_400: Final = "HEPH-IDEMP-400"
IDEMP_409: Final = "HEPH-IDEMP-409"
IDEMP_422: Final = "HEPH-IDEMP-422"
MONEY_422: Final = "HEPH-MONEY-422"
MONEY_409: Final = "HEPH-MONEY-409"
WH_401: Final = "HEPH-WH-401"

# code -> (HTTP status, title)
REGISTRY: dict[str, tuple[int, str]] = {
    "HEPH-GEN-500": (500, "Internal error"),
    "HEPH-VAL-422": (422, "Validation failed"),
    "HEPH-NF-404": (404, "Resource not found"),
    "HEPH-AUTH-401": (401, "Authentication required"),
    "HEPH-AUTH-403": (403, "Permission denied"),
    "HEPH-RATE-429": (429, "Rate limit exceeded"),
    "HEPH-IDEMP-400": (400, "Idempotency key missing or malformed"),
    "HEPH-IDEMP-409": (409, "Original request still in flight"),
    "HEPH-IDEMP-422": (422, "Idempotency key reused with a different payload"),
    "HEPH-MONEY-422": (422, "Invalid money amount"),
    "HEPH-MONEY-409": (409, "Currency mismatch"),
    "HEPH-WH-401": (401, "Webhook signature invalid or expired"),
}
