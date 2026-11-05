"""Telemetry attribute names generated from conventions/attributes.yaml.

GENERATED FILE - do not edit by hand. Regenerate with
``uv run tools/gen_conventions.py``; CI runs ``--check``. Attribute names live
only in ``conventions/attributes.yaml``.
"""

from typing import Final

TENANT_ID: Final = "tenant.id"
USER_ID: Final = "user.id"
IDEMPOTENCY_KEY: Final = "idempotency.key"
JOB_NAME: Final = "job.name"
WEBHOOK_PROVIDER: Final = "webhook.provider"
MONEY_CURRENCY: Final = "money.currency"
HEPH_ERROR_CODE: Final = "heph.error.code"

# every registered attribute name, in registry order
ALL_ATTRIBUTES: Final[tuple[str, ...]] = (
    "tenant.id",
    "user.id",
    "idempotency.key",
    "job.name",
    "webhook.provider",
    "money.currency",
    "heph.error.code",
)

# attributes marked pii: true; redacted from logs by default
PII_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {
        "user.id",
    }
)
