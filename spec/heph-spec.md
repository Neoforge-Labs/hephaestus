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
- Idempotency records carry a 60 second default lease; 5xx and raised errors release the record, status below 500 is stored and replayed (2.7, 2.8).
- Integer literals above 2^53-1 are rejected with `HEPH-VAL-422`, never rounded; literals with a fraction or exponent follow RFC 8785 number serialisation (4.3).
- Money `amount` is a string matching `^(0|-?[1-9][0-9]*)$`; JSON numbers are rejected (3.2, 3.4).

## 1. Errors

**Profiles:** RFC 9457 (Problem Details for HTTP APIs).

1.1. Every error response MUST use the media type `application/problem+json` and the HTTP status of the registry entry for its code.

1.2. The body MUST contain the RFC 9457 members `type`, `title`, `status` and `detail`, and the extension members `code` and `trace_id`.

1.3. `code` MUST be a code from `spec/errors.yaml`. Codes match `^HEPH-[A-Z]{2,6}-[0-9]{3}$` (ASCII digits only; the whole string must match, with no trailing newline); the middle segment is the entry's `area`. Implementations MUST NOT emit a code absent from the registry.

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

2.1. Clients send the key in the `Idempotency-Key` header. An `Idempotency-Key` MUST be 1 to 255 characters of printable ASCII (VCHAR, 0x21-0x7E), with no whitespace. A missing key, an empty key, or a key violating this syntax MUST be rejected with `HEPH-IDEMP-400` by an endpoint that requires a key. An endpoint that does not require an `Idempotency-Key` MUST ignore a malformed one rather than failing the request. Keys MUST be opaque (a UUID or similar); clients MUST NOT embed personal data in an `Idempotency-Key`, because the key is recorded as the telemetry attribute `idempotency.key` and is not redacted.

2.2. **Fingerprint.** The fingerprint identifies the request a key was first used with. It is computed in four steps:

1. Build a JSON object with exactly three members, named `method`, `path` and `body`:
   - `method`: the HTTP method as an uppercase ASCII string, for example `"POST"`.
   - `path`: the request target in origin-form exactly as received: the path followed, if a query string is present, by `?` and the query string. It is the raw request target: implementations MUST NOT normalise it (no percent-decoding, case-folding, query reordering or slash collapsing), so two orderings of one query yield different fingerprints. It excludes scheme, host and fragment. An empty query (a bare `?`) is kept as received.
   - `body`: if the request has no body or a zero-length body, the JSON value `null`. If the body is JSON, the parsed JSON value; a body with a JSON media type that does not parse, or that RFC 8785 cannot represent (4.3), MUST be rejected with `HEPH-VAL-422`. A media type is JSON when its type/subtype, compared case-insensitively and ignoring parameters (so `application/json; charset=utf-8` is JSON), is `application/json` or its subtype ends in `+json`. For any other media type, the string `"sha256:"` followed by the lowercase hex SHA-256 of the raw body bytes.
2. Serialise the object with RFC 8785 JCS (section 4), giving a UTF-8 string.
3. Compute SHA-256 over the bytes of that UTF-8 string, with no added newline or BOM.
4. The fingerprint is `sha256:` followed by the 64-character lowercase hex digest.

For `POST /v1/charges` with body `{"b":1,"a":2}` the JCS string is `{"body":{"a":2,"b":1},"method":"POST","path":"/v1/charges"}` and the fingerprint is `sha256:9d7a9f8a22e4d35d3efc80eafe7f0026713f6ad9ba4a3abd5c025e92036fd6eb`. Check it with `printf '%s' '<jcs string>' | shasum -a 256`. Headers (including the key itself) are not part of the fingerprint.

2.3. **Storage.** A record is unique on `(scope, key)`, where `scope` is the tenant id of the authenticated principal when it has one and the empty string otherwise (never a client-supplied header or body field). It stores the fingerprint, state (`in_flight` or `completed`), a lease expiry while `in_flight`, and once completed the response status and body. Record creation MUST be atomic with the uniqueness check: of two concurrent first requests with the same `(scope, key)`, exactly one proceeds.

2.4. **Replay.** If a `completed` record exists and the fingerprint matches, the server MUST NOT run the operation again. It MUST return the stored status and body with the additional header `Idempotent-Replayed: true`.

2.5. If a record exists in state `in_flight` and its lease has not expired, the server MUST respond `HEPH-IDEMP-409`.

2.6. If a record exists and its fingerprint differs, the server MUST respond `HEPH-IDEMP-422`, whatever its state and whether or not an `in_flight` lease has expired. This takes precedence over 2.5: when the original is still in flight and the fingerprint also differs, the answer is `HEPH-IDEMP-422`, because it names a client bug rather than a retry-later condition.

2.7. **Retention and lease.** The default retention is 24 hours from creation and MAY be configured longer. After expiry a key is treated as new. The default `in_flight` lease is 60 seconds and is configurable.

2.8. **Lifecycle.** A request that creates a record starts it `in_flight` with a lease. When the operation produces a response with status below 500, the record MUST become `completed` and store that response; 4xx responses are stored and replayed like any other, because they are real outcomes of the operation. When the operation produces a response with status 500 or above, or the handler raises, the record MUST be released, meaning it is removed (not left `in_flight`), so the client can retry. A request that finds an `in_flight` record whose lease has expired and whose fingerprint equals the stored one (a genuine retry) MUST be allowed to proceed and take over the record with a new lease, so a crashed worker cannot wedge a key for the retention window. A request with a differing fingerprint is answered by 2.6 instead. The stored fingerprint is never replaced for the life of the record: one key means one payload for the whole retention window, and an expired lease says only that the previous attempt's outcome is unknown, not that the client's payload may change.

## 3. Money on the wire

**Original.**

3.1. A monetary value is a JSON object with exactly two members:

```json
{"amount": "1999", "currency": "USD"}
```

3.2. `amount` is a JSON **string**: an integer count of the currency's minor units in base 10, so that it survives JavaScript numbers. It MUST match `^(0|-?[1-9][0-9]*)$` (ASCII digits only, no `+`, no leading zeros, no whitespace, no decimal point, no exponent, and no `-0`). It MUST fit in a signed 64-bit integer. Anything else is rejected with `HEPH-MONEY-422`.

3.3. `currency` MUST be an alphabetic code with a defined minor-unit exponent; three uppercase ASCII letters is necessary but not sufficient. The exponent is the one given in `conformance/money/currency.json`, which is the normative exponent table for the currencies Phase 1 supports (for example `USD` 2, `JPY` 0, `KWD` 3). That file records its derivation: ISO 4217 List One as published by SIX Group, retrieved on 2026-11-04, with each exponent hand-derived from the table. An unknown code (for example `XYZ`), or a code with no defined exponent (`XXX`, `XAU`, `XTS`, `XDR` and the other non-currency codes), MUST be rejected with `HEPH-MONEY-422`. A change to the accepted set requires a spec version bump and updated conformance vectors.

A wire object that violates 3.1 (missing member, extra member, or a value of the wrong JSON type) MUST also be rejected with `HEPH-MONEY-422`. `HEPH-MONEY-409` is reserved for a currency mismatch between two amounts in one operation.

3.4. A JSON number in `amount` MUST be rejected with `HEPH-MONEY-422`. Floating point MUST NOT be used to parse, hold or compute money.

3.5. Implementations hold money as a signed 64-bit integer of minor units plus a currency. Arithmetic across two currencies MUST fail with `HEPH-MONEY-409`. Overflow MUST fail rather than wrap.

3.6. **Parsing and formatting decimals.** Parsing a decimal string such as `"19.99"` (a human-facing input, not the wire format) MUST be strict ASCII and MUST reject more fractional digits than the currency's exponent with `HEPH-MONEY-422`, unless the caller supplies an explicit rounding mode. The rule is about the digit count as written, not the value: `reject` rejects any input whose fractional digit count exceeds the exponent, including trailing zeros (KES `10.290` is rejected), and supplying a rounding mode is how a caller accepts such input. The decimal input grammar is: an optional `-`, one or more ASCII digits, then optionally `.` followed by one or more ASCII digits; nothing else is accepted (no `+`, whitespace, exponent, grouping separator or non-ASCII digit). Leading zeros are permitted in the integer part (`"007"` is 7), and a negative zero form (`"-0"`, `"-0.00"`) parses to 0, because minor units are signed 64-bit integers and have no negative zero. This is the grammar for decimal input only: the stricter `^(0|-?[1-9][0-9]*)$` rule in 3.2 governs the wire `amount` and is deliberately different. A rounding mode applies only when the input has more fractional digits than the exponent, and is one of:

- `half_up`: a tie (exactly half a minor unit) rounds away from zero; anything else rounds to the nearest minor unit.
- `half_even`: a tie rounds to the even minor unit; anything else rounds to the nearest.
- `down`: truncates toward zero, so the magnitude never increases (`-10.295` KES is `-1029`, not `-1030`).

Formatting minor units as a decimal string produces exactly `exponent` fractional digits, no grouping separators, a `-` prefix for negative values, and never `-0`. Formatting `1` with exponent 3 gives `0.001`; with exponent 0 there is no decimal point.

3.7. **Allocation.** Allocating an amount by a list of ratios uses the largest-remainder method. Ratios are non-negative integers (negative ratios are not representable); the list MUST be non-empty and at least one ratio MUST be non-zero, otherwise the call is rejected with `HEPH-MONEY-422`. A negative amount allocates its absolute value and negates each part. For a non-negative amount, each part's exact share is `amount * ratio / sum(ratios)`; take its floor, then distribute the leftover minor units one at a time to the parts with the largest fractional remainders, ties going to the lower index. The parts always sum to the original amount exactly, and every part carries the original currency. For example 100 allocated by `[3,1,2]` is `[50,17,33]`, not `[51,16,33]`.

## 4. Canonical JSON and hashing

**Profiles:** RFC 8785 (JSON Canonicalization Scheme).

4.1. Canonical JSON is RFC 8785 output. Hashes of JSON values are taken over the UTF-8 bytes of that output.

4.2. A content hash is the string `sha256:` followed by the lowercase hex SHA-256 digest (64 characters). Uppercase hex and other prefixes are invalid.

4.3. Number handling depends on how the number is written, not on how large its value is. The core returns `HEPH-VAL-422` for every rejection in this section; nothing is silently rounded or normalised.

- A JSON number written as an **integer literal** (no fraction and no exponent) MUST have magnitude at most 2^53-1, that is 9007199254740991, the largest accepted integer literal. A larger integer literal MUST be rejected: `9007199254740992`, `9007199254740993` and `-9007199254740993` are rejected.
- A JSON number written **with a fraction or an exponent** is parsed as an IEEE-754 double and serialised by the RFC 8785 ECMAScript `Number::toString` rules. Rounding to the nearest double is expected and permitted here. For example `1e20` becomes `100000000000000000000`, `1e21` becomes `1e+21`, `0.1` stays `0.1`, and `123456789012345678901234567890.5` becomes `1.2345678901234568e+29`. An integer-valued literal with a fraction or exponent (such as `1e20`) is therefore not an integer literal for this rule. `-0` is serialised as `0`.
- Non-finite values (NaN, +Infinity, -Infinity), lone surrogates and duplicate object member names MUST be rejected.
- Nesting depth is bounded: a top-level scalar has depth 0, and every array or object entered adds 1 to the depth. A document whose maximum depth exceeds 128 MUST be rejected, so `[` repeated 128 times closed by 128 `]` is accepted and 129 is rejected. The bound exists so that a hostile document cannot exhaust the stack of any implementation.

This matches the `rfc8785` reference package, which raises on integer literals outside the safe-integer domain.

## 5. Webhooks

**Profiles:** Standard Webhooks.

5.1. Messages carry the headers `webhook-id`, `webhook-timestamp` (integer seconds since the Unix epoch) and `webhook-signature`.

5.2. Secrets follow Standard Webhooks: a secret may carry the optional `whsec_` prefix, and the HMAC key is the base64-decoded remainder. The signed content is `<webhook-id>.<webhook-timestamp>.<raw body>`. The signature is HMAC-SHA256 over it, base64-encoded, and `webhook-signature` carries it as `v1,<base64>`.

5.3. `webhook-signature` MAY hold several space-separated signatures. A message is valid if any signature of a known version verifies. Signatures of unknown versions MUST be ignored, not treated as failures.

5.4. Verification MUST use constant-time comparison.

5.5. The timestamp tolerance is 300 seconds in either direction, and the boundary is inclusive: a timestamp is accepted when `|now - timestamp| <= 300` and rejected when the difference exceeds 300 (301 seconds old, or 301 seconds in the future, is rejected). A timestamp outside it MUST be rejected even if the signature verifies.

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
