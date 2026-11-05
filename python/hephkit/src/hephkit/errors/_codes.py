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
    "HEPH-GEN-500": "Something went wrong on our side. Try again later, and quote the trace_id from this response if you contact support.",
    "HEPH-VAL-422": "The request failed validation. Each offending field and the rule it broke is listed under errors.",
    "HEPH-NF-404": "The requested resource was not found.",
    "HEPH-AUTH-401": "Authentication is required. Your credentials are missing, malformed or expired.",
    "HEPH-AUTH-403": "You are authenticated but do not have permission to perform this action.",
    "HEPH-RATE-429": "Too many requests. Wait for the time given in the Retry-After header before trying again.",
    "HEPH-IDEMP-400": "The Idempotency-Key header is missing, empty, or not 1-255 printable ASCII characters without whitespace.",
    "HEPH-IDEMP-409": "A request with this key is still being processed. Retry after it completes.",
    "HEPH-IDEMP-422": "This Idempotency-Key was already used for a different request. Use a new key for a new request.",
    "HEPH-MONEY-422": "The amount is not a valid integer minor-units string, or has more precision than its currency allows.",
    "HEPH-MONEY-409": "This operation mixes two different currencies; both amounts must use the same currency.",
    "HEPH-WH-401": "The webhook signature is invalid or has expired.",
}
