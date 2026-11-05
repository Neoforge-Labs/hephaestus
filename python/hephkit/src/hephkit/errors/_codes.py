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

# code -> guidance for the caller, used as the default problem `detail`
DETAIL_HINTS: dict[str, str] = {
    "HEPH-GEN-500": "An unexpected failure. Never include internals; give the trace_id so the operator can find it.",
    "HEPH-VAL-422": "Name the offending field and the rule it broke, not the submitted value.",
    "HEPH-NF-404": "Name the resource type. Also use this when the caller may not learn that a resource exists.",
    "HEPH-AUTH-401": "Credentials are missing, malformed or expired. Do not say which part was wrong.",
    "HEPH-AUTH-403": "The caller is authenticated but not allowed. Name the missing permission, not the resource contents.",
    "HEPH-RATE-429": "Say when to retry; the response also carries a Retry-After header.",
    "HEPH-IDEMP-400": "The key is missing, empty, or not 1-255 printable ASCII characters without whitespace.",
    "HEPH-IDEMP-409": "A request with this key is still being processed. Retry after it completes.",
    "HEPH-IDEMP-422": "The key was already used for a request with a different fingerprint. Use a new key.",
    "HEPH-MONEY-422": "The amount is not a valid integer-minor-units string, or has excess precision for its currency.",
    "HEPH-MONEY-409": "The operation mixes two currencies. Name both currency codes.",
    "HEPH-WH-401": "No signature verified, or the timestamp is outside the 300 second tolerance. Do not say which.",
}
