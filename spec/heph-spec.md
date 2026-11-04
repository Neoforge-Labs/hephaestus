# heph-spec

- **Version:** 0.1.0
- **Status:** Draft for implementation in Phase 1; every module implementing it is `experimental`.
- **Registries:** `spec/errors.yaml` (error codes), `conventions/attributes.yaml` (telemetry attributes).

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119 and RFC 8174. Where this document profiles a standard, the standard governs everything this document does not restate. Four parts are original: the error-code registry (section 1), idempotency storage and replay (section 2), money on the wire (section 3) and the provenance record (section 7).

## Decisions this version settles

- Idempotency records are scoped by `(tenant id or "", key)`, so keys never collide across tenants (2.3).
- A fingerprint mismatch returns `HEPH-IDEMP-422` even while the original is in flight (2.6).
- Fingerprint `path` is the raw request target including the query string, never normalised (2.2).
- Fingerprint `body` is `null` when empty, and `sha256:` plus the hex of the raw bytes for non-JSON media types (2.2).
- Money `amount` is a string matching `^(0|-?[1-9][0-9]*)$`; JSON numbers are rejected (3.2, 3.4).

## 1. Errors

**Profiles:** RFC 9457 (Problem Details for HTTP APIs).

1.1. Every error response MUST use the media type `application/problem+json` and the HTTP status of the registry entry for its code.

1.2. The body MUST contain the RFC 9457 members `type`, `title`, `status` and `detail`, and the extension members `code` and `trace_id`.

1.3. `code` MUST be a code from `spec/errors.yaml`. Codes match `^HEPH-[A-Z]{2,6}-\d{3}$`; the middle segment is the entry's `area`. Implementations MUST NOT emit a code absent from the registry.

1.4. `type` MUST be `https://heph.neoforgelabs.tech/errors/<code>`, for example `https://heph.neoforgelabs.tech/errors/HEPH-VAL-422`.

1.5. `title` MUST equal the registry `title`. `status` MUST equal the registry `status` and the HTTP status line.

1.6. `trace_id` MUST be the W3C Trace Context trace id (32 lowercase hex characters) of the request's active span, or omitted only when no trace is active.

1.7. `detail` is for the caller. It MUST NOT contain stack traces, SQL, file paths, secrets or personal data, and SHOULD follow the registry `detail_hint`.

1.8. A registry entry is permanent: a code's meaning and status MUST NOT change after release. A retired code stays in the registry.

Example:

```json
{
  "type": "https://heph.neoforgelabs.tech/errors/HEPH-IDEMP-409",
  "title": "Original request still in flight",
  "status": 409,
  "detail": "A request with this Idempotency-Key is still being processed.",
  "code": "HEPH-IDEMP-409",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"
}
```

## 2. Idempotency

**Profiles:** the IETF `Idempotency-Key` HTTP header field draft (draft-ietf-httpapi-idempotency-key-header).

2.1. Clients send the key in the `Idempotency-Key` header. An endpoint that requires a key and receives none MUST respond `HEPH-IDEMP-400`. Keys MUST be opaque (a UUID or similar); clients MUST NOT embed personal data in an `Idempotency-Key`, because the key is recorded as the telemetry attribute `idempotency.key` and is not redacted.

2.2. **Fingerprint.** The fingerprint identifies the request a key was first used with. It is computed in four steps:

1. Build a JSON object with exactly three members, named `method`, `path` and `body`:
   - `method`: the HTTP method as an uppercase ASCII string, for example `"POST"`.
   - `path`: the request target in origin-form exactly as received: the path followed, if a query string is present, by `?` and the query string. It is the raw request target: implementations MUST NOT normalise it (no percent-decoding, case-folding, query reordering or slash collapsing), so two orderings of one query yield different fingerprints. It excludes scheme, host and fragment. An empty query (a bare `?`) is kept as received.
   - `body`: if the request has no body or a zero-length body, the JSON value `null`. If the body is JSON (media type `application/json` or `+json`), the parsed JSON value. For any other media type, the string `"sha256:"` followed by the lowercase hex SHA-256 of the raw body bytes.
2. Serialise the object with RFC 8785 JCS (section 4), giving a UTF-8 string.
3. Compute SHA-256 over the bytes of that UTF-8 string, with no added newline or BOM.
4. The fingerprint is `sha256:` followed by the 64-character lowercase hex digest.

For `POST /v1/charges` with body `{"b":1,"a":2}` the JCS string is `{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges"}`. Headers (including the key itself) are not part of the fingerprint.

2.3. **Storage.** A record is unique on `(scope, key)`, where `scope` is the tenant id when the request has one and the empty string otherwise. It stores the fingerprint, state (`in_flight` or `completed`), and once completed the response status and body. Record creation MUST be atomic with the uniqueness check: of two concurrent first requests with the same `(scope, key)`, exactly one proceeds.

2.4. **Replay.** If a `completed` record exists and the fingerprint matches, the server MUST NOT run the operation again. It MUST return the stored status and body with the additional header `Idempotent-Replayed: true`.

2.5. If a record exists in state `in_flight`, the server MUST respond `HEPH-IDEMP-409`.

2.6. If a record exists and its fingerprint differs, the server MUST respond `HEPH-IDEMP-422`, whatever its state. This takes precedence over 2.5: when the original is still in flight and the fingerprint also differs, the answer is `HEPH-IDEMP-422`, because it names a client bug rather than a retry-later condition.

2.7. **Retention.** Records are kept for at least 24 hours from creation by default. After expiry a key is treated as new. Deployments MAY configure a longer retention.

## 3. Money on the wire

**Original.**

3.1. A monetary value is a JSON object with exactly two members:

```json
{"amount": "1999", "currency": "USD"}
```

3.2. `amount` is a JSON **string**: an integer count of the currency's minor units in base 10, so that it survives JavaScript numbers. It MUST match `^(0|-?[1-9][0-9]*)$` (ASCII digits only, no `+`, no leading zeros, no whitespace, no decimal point, no exponent, and no `-0`). It MUST fit in a signed 64-bit integer. Anything else is rejected with `HEPH-MONEY-422`.

3.3. `currency` is an ISO 4217 alphabetic code, three uppercase ASCII letters. Its minor-unit exponent is taken from ISO 4217 (`USD` 2, `JPY` 0, `KWD` 3).

3.4. A JSON number in `amount` MUST be rejected with `HEPH-MONEY-422`. Floating point MUST NOT be used to parse, hold or compute money.

3.5. Implementations hold money as a signed 64-bit integer of minor units plus a currency. Arithmetic across two currencies MUST fail with `HEPH-MONEY-409`. Overflow MUST fail rather than wrap.

3.6. Parsing a decimal string such as `"19.99"` (a human-facing input, not the wire format) MUST be strict ASCII and MUST reject more fractional digits than the currency's exponent with `HEPH-MONEY-422`, unless the caller supplies an explicit rounding mode.

## 4. Canonical JSON and hashing

**Profiles:** RFC 8785 (JSON Canonicalization Scheme).

4.1. Canonical JSON is RFC 8785 output. Hashes of JSON values are taken over the UTF-8 bytes of that output.

4.2. A content hash is the string `sha256:` followed by the lowercase hex SHA-256 digest (64 characters). Uppercase hex and other prefixes are invalid.

4.3. Inputs that RFC 8785 cannot represent (non-finite numbers, lone surrogates) and duplicate object member names MUST be rejected rather than normalised.

## 5. Webhooks

**Profiles:** Standard Webhooks.

5.1. Messages carry the headers `webhook-id`, `webhook-timestamp` (integer seconds since the Unix epoch) and `webhook-signature`.

5.2. The signed content is `<webhook-id>.<webhook-timestamp>.<raw body>`. The signature is HMAC-SHA256 over it, base64-encoded, and `webhook-signature` carries it as `v1,<base64>`.

5.3. `webhook-signature` MAY hold several space-separated signatures. A message is valid if any signature of a known version verifies. Signatures of unknown versions MUST be ignored, not treated as failures.

5.4. Verification MUST use constant-time comparison.

5.5. The timestamp tolerance is 300 seconds in either direction. A timestamp outside it MUST be rejected even if the signature verifies.

5.6. A failure to verify, for any reason, is `HEPH-WH-401`. The response MUST NOT reveal which check failed.

## 6. Telemetry

**Profiles:** OpenTelemetry semantic conventions.

6.1. Implementations use OpenTelemetry semantic-convention names where one exists. Names in `conventions/attributes.yaml` are the shared names for concepts semantic conventions do not cover, and MUST be used verbatim for those concepts.

6.2. Attributes with `pii: true` MUST be redacted from log output and MUST NOT be sent as metric labels.

6.3. Logs MUST carry `trace_id` (as in 1.6). When an error is returned or recorded, the span MUST carry `heph.error.code`.

## 7. Provenance record

**Status: draft.** Not implemented in Phase 1; fields may change before it is promoted.

7.1. A provenance record describes one research run with these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `run_id` | string | Unique identifier of the run |
| `config_hash` | string | Content hash (4.2) of the canonical run configuration |
| `data_hash` | string | Content hash (4.2) of the input data |
| `code_sha` | string | Git commit SHA of the code that ran |
| `class` | string | `deterministic` or `provenance-only` |

7.2. `deterministic` runs re-execute from `config_hash` and `data_hash` to an identical result. `provenance-only` runs record how a result was produced but are not expected to reproduce it exactly.
