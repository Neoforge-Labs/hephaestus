# heph-spec

- **Version:** 0.5.0
- **Status:** Draft for implementation in Phase 1; every module implementing it is `experimental`.
- **Registries:** `spec/errors.yaml` (error codes), `conventions/attributes.yaml` (telemetry attributes), `spec/currencies.yaml` (ISO 4217 minor units, with its publication pinned by `spec/currencies.source.yaml`).

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119 and RFC 8174. Where this document profiles a standard, the standard governs everything this document does not restate. Six parts are original: the error-code registry (section 1), idempotency storage and replay (section 2), money on the wire (section 3), the provenance record (section 7), the run record (section 8) and the replay and diff of a run (section 9).

## Decisions this version settles

- The problem `type` host is `hephkit.dev`: `type` is `https://hephkit.dev/errors/<code>` (1.4, ADR 0019).
- Idempotency records are scoped by `(tenant id or "", key)`, so keys never collide across tenants (2.3).
- A fingerprint mismatch returns `HEPH-IDEMP-422` even while the original is in flight (2.6).
- Fingerprint `path` is the raw request target including the query string, never normalised (2.2).
- Fingerprint `body` is `null` when empty, and `sha256:` plus the hex of the raw bytes for non-JSON media types (2.2).
- Idempotency records carry a 60 second default lease. A response with status below 500 is stored and replayed; a response of 500 or above, or a handler that raises, releases the record. A raised error that is itself the sub-500 response the client receives, as on an HTTP route, is stored like any other 4xx; an event handler answers no client, so a raised error there always releases and the broker redelivers (2.7, 2.8).
- A record whose `in_flight` lease is still live is never treated as new, however old it is: retention expiry applies only when no attempt holds the key (2.7).
- Taking over an expired lease transfers ownership of the record, and an attempt that has been superseded may neither complete nor release it (2.8).
- Integer literals above 2^53-1 are rejected with `HEPH-VAL-422`, never rounded; literals with a fraction or exponent follow RFC 8785 number serialisation (4.3).
- Money `amount` is a string matching `^(0|-?[1-9][0-9]*)$`; JSON numbers are rejected (3.2, 3.4).
- Fractional digits beyond a currency's exponent are accepted when every one of them is zero, because the value is preserved exactly; a non-zero digit beyond the exponent still needs a rounding mode (3.6, ADR 0016).
- Ordering two amounts of different currencies is `HEPH-MONEY-409`, never a boolean, so ordering is a fallible operation and is never offered through an interface that cannot fail; equality keeps answering every pair (3.8).
- The accepted currency set is the whole of ISO 4217 List One, a code being accepted if and only if List One gives it a numeric minor-unit field, which includes the funds codes and excludes the `N.A.` codes (3.3, ADR 0017).
- The provenance record (section 7) is normative, and its fields split by whether they decide re-execution or merely describe it: `config_hash`, `data_hash`, `deps_hash` and `code_sha` form the determinism contract, while `environment` is descriptive and is never compared (7.1, 7.2, ADR 0024).
- A run is `provenance-only` unless a git commit names the code, the working tree is clean and a dependency lockfile exists; `code_sha` is `null` exactly when git `HEAD` resolves to no commit, never merely because the tree is dirty, and `deps_hash` exactly when there is no lockfile, and `environment` never carries a hostname, a username or a filesystem path (7.1, 7.3, 7.5, ADR 0024).
- A run record is a directory holding `provenance.json`, `rows.jsonl` and `summary.json`, every document canonical JSON; a row is durable before the call that appended it returns, so a crash costs the row in flight and no completed cell (8.1, 8.3).
- A record that cannot be written is a failed run: every write failure is raised and fails the run, and an implementation never warns and continues, writes elsewhere, drops a row or reports a number the record does not hold (8.5).
- The summary is an index derived from the rows, a reader recomputes it and refuses a record whose stored summary disagrees, and a record with no summary is unfinished rather than invalid (8.4).
- A record carries no wall-clock time in any of its documents, because a clock reading in a compared position would make every replay diverge (8.1).
- A non-finite value is recorded as `{"nonfinite": "NaN"}`, `{"nonfinite": "Infinity"}` or `{"nonfinite": "-Infinity"}`, never as a bare `NaN` or `Infinity` token, which 4.3 rejects and no conforming parser accepts (8.2).
- A replay compares the four determinism-contract members of the provenance record and the rows, by cell name and value name. It compares `environment`, `run_id`, `class`, the summary and the order of the rows not at all, each for a reason of its own (9.1).
- A difference names a position — a cell and a value name, or a determinism-contract member — and the two values found there; a `null` says the position is absent, since a row value is never null, and a report matched exactly when it carries no difference (9.2).
- `NaN` compares **equal** to `NaN` for the purposes of a replay, because 8.2's wrapper is compared by the value it names and a record must compare equal to itself (9.3).
- Two finite numbers are equal exactly when `|a - b| <= max(1e-9 * max(|a|, |b|), 1e-12)`: relative so that 7.2's second machine can satisfy the contract, absolute so that a value near zero is comparable at all, symmetric, and not loosenable per run, cell or value (9.3).
- A divergence is reported, never raised: a replay produces its difference report, and a caller that needs a refusal derives one from it under `HEPH-LAB-409` (9.1, 9.4).
- Section 10 is reserved: dataset manifests, and with them the digest scope of `data_hash`, are not yet specified, and an implementation chooses no scope of its own meanwhile (10, 7.1).

## 1. Errors

**Profiles:** RFC 9457 (Problem Details for HTTP APIs).

1.1. Every error response MUST use the media type `application/problem+json` and the HTTP status of the registry entry for its code.

1.2. The body MUST contain the RFC 9457 members `type`, `title`, `status` and `detail`, and the extension members `code` and `trace_id`.

1.3. `code` MUST be a code from `spec/errors.yaml`. Codes match `^HEPH-[A-Z]{2,6}-[0-9]{3}$` (ASCII digits only; the whole string must match, with no trailing newline); the middle segment is the entry's `area`. Implementations MUST NOT emit a code absent from the registry.

1.4. `type` MUST be `https://hephkit.dev/errors/<code>`, for example `https://hephkit.dev/errors/HEPH-VAL-422`.

1.5. `title` MUST equal the registry `title`. `status` MUST equal the registry `status` and the HTTP status line.

1.6. `trace_id` MUST be the W3C Trace Context trace id (32 lowercase hex characters) of the request's active span, or omitted only when no trace is active.

1.7. `detail` is for the caller. It MUST NOT contain stack traces, SQL, file paths, secrets or personal data. When the implementation supplies no more specific text, `detail` MUST be the registry `detail_hint`, which is written for the caller and sent verbatim.

1.8. A registry entry is permanent: a code's meaning and status MUST NOT change after release. A retired code stays in the registry. Each registry entry carries a caller-facing `detail_hint` (see 1.7) and a developer-facing `guidance`, which explains the cause and the fix to the implementer, is never sent on the wire, and is published on the docs page for the code.

Example:

```json
{
  "type": "https://hephkit.dev/errors/HEPH-IDEMP-409",
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

2.7. **Retention and lease.** The default retention is 24 hours from creation and MAY be configured longer. After expiry a key is treated as new. A record whose `in_flight` lease has not expired MUST NOT be treated as new, even once its retention has elapsed: retention expiry applies only when no attempt holds the key. Otherwise a record taken over near the retention boundary — 2.8 does not reset the creation time — could be reset while its handler is still running, and two handlers would hold one key. The default `in_flight` lease is 60 seconds and is configurable.

2.8. **Lifecycle.** A request that creates a record starts it `in_flight` with a lease. When the operation produces a response with status below 500, the record MUST become `completed` and store that response; 4xx responses are stored and replayed like any other, because they are real outcomes of the operation. When the operation produces a response with status 500 or above, or the handler raises, the record MUST be released, meaning it is removed (not left `in_flight`), so the client can retry. A request that finds an `in_flight` record whose lease has expired and whose fingerprint equals the stored one (a genuine retry) MUST be allowed to proceed and take over the record with a new lease, so a crashed worker cannot wedge a key for the retention window. Taking over a record transfers ownership of it. An attempt that has been superseded MUST NOT complete or release the record: only the attempt that currently holds it may do so. A request with a differing fingerprint is answered by 2.6 instead. The stored fingerprint is never replaced for the life of the record: one key means one payload for the whole retention window, and an expired lease says only that the previous attempt's outcome is unknown, not that the client's payload may change.

## 3. Money on the wire

**Original.**

3.1. A monetary value is a JSON object with exactly two members:

```json
{"amount": "1999", "currency": "USD"}
```

3.2. `amount` is a JSON **string**: an integer count of the currency's minor units in base 10, so that it survives JavaScript numbers. It MUST match `^(0|-?[1-9][0-9]*)$` (ASCII digits only, no `+`, no leading zeros, no whitespace, no decimal point, no exponent, and no `-0`). It MUST fit in a signed 64-bit integer. Anything else is rejected with `HEPH-MONEY-422`.

3.3. `currency` MUST be an alphabetic code with a defined minor-unit exponent; three uppercase ASCII letters is necessary but not sufficient. The accepted set is the whole of ISO 4217 List One, the standard's current currency and funds code list: a code is accepted **if and only if** List One gives it a numeric minor-unit field, and its exponent is that field (for example `USD` 2, `JPY` 0, `KWD` 3, `CLF` 4). A code List One publishes with a minor-unit field of `N.A.` has no exponent and MUST be rejected with `HEPH-MONEY-422`; so MUST a code that is not in List One at all, whether it was never assigned (for example `XYZ`) or the standard has retired it to the historical list (for example `BGN` after Amendment 180). Because the rule is mechanical, the funds codes (`CHE`, `CHW`, `USN`, `MXV`, `COU`, `BOV`, `CLF`, `UYI`, `UYW`) are accepted and the non-currency codes (`XXX`, `XAU`, `XTS`, `XDR` and the rest) are rejected; ADR 0017 records why that boundary is the right one. ISO defines no exponent-1 code, so the exponents in use are 0, 2, 3 and 4.

The normative registry is `spec/currencies.yaml`, which transcribes List One; `core/hephkit-core/src/money/currency_table.rs` is generated from it by `tools/gen_currencies.py` and MUST NOT be edited by hand. The publication the registry came from is pinned by sha256 in `spec/currencies.source.yaml`, and `tools/gen_currencies.py --verify-source <file>` asserts both that a local copy of List One hashes to that pin and that the registry is exactly what those bytes derive to, code by code, including the rows published as `N.A.` Re-transcription is therefore a mechanical diff rather than a fresh act of trust, and every exponent an implementation relies on is reproducible from the standard without trusting this repository. The published file itself is not committed, because its terms of use do not clearly permit redistribution; `spec/currencies.source.yaml` records that reasoning. `conformance/money/currency.json` pins a representative sample of the accepted codes together with every rejection boundary, and is what a new implementation is tested against. A change to the accepted set requires a spec version bump and updated conformance vectors, and is made by re-transcribing a newer List One, never by editing one code.

A wire object that violates 3.1 (missing member, extra member, or a value of the wrong JSON type) MUST also be rejected with `HEPH-MONEY-422`. `HEPH-MONEY-409` is reserved for a currency mismatch between two amounts in one operation.

3.4. A JSON number in `amount` MUST be rejected with `HEPH-MONEY-422`. Floating point MUST NOT be used to parse, hold or compute money.

3.5. Implementations hold money as a signed 64-bit integer of minor units plus a currency. Arithmetic across two currencies MUST fail with `HEPH-MONEY-409`. Overflow MUST fail rather than wrap.

3.6. **Parsing and formatting decimals.** Parsing a decimal string such as `"19.99"` (a human-facing input, not the wire format) MUST be strict ASCII and MUST reject with `HEPH-MONEY-422` any input carrying more precision than the currency's exponent can hold, unless the caller supplies an explicit rounding mode. The rule is about the value, not the digit count as written: fractional digits beyond the exponent are accepted when every one of them is zero, because dropping them preserves the value exactly (KES `10.290` is accepted and is 10.29, minor 1029), and `reject` rejects an input only when a digit beyond the exponent is non-zero, which is where a rounding mode becomes the way a caller accepts the input. The decimal input grammar is: an optional `-`, one or more ASCII digits, then optionally `.` followed by one or more ASCII digits; nothing else is accepted (no `+`, whitespace, exponent, grouping separator or non-ASCII digit). Leading zeros are permitted in the integer part (`"007"` is 7), and a negative zero form (`"-0"`, `"-0.00"`) parses to 0, because minor units are signed 64-bit integers and have no negative zero. This is the grammar for decimal input only: the stricter `^(0|-?[1-9][0-9]*)$` rule in 3.2 governs the wire `amount` and is deliberately different. A rounding mode applies only when a fractional digit beyond the exponent is non-zero; an input whose excess digits are all zero parses to the same minor units under every mode. A rounding mode is one of:

- `half_up`: a tie (exactly half a minor unit) rounds away from zero; anything else rounds to the nearest minor unit.
- `half_even`: a tie rounds to the even minor unit; anything else rounds to the nearest.
- `down`: truncates toward zero, so the magnitude never increases (`-10.295` KES is `-1029`, not `-1030`).

Formatting minor units as a decimal string produces exactly `exponent` fractional digits, no grouping separators, a `-` prefix for negative values, and never `-0`. Formatting `1` with exponent 3 gives `0.001`; with exponent 0 there is no decimal point.

*Implementation note (non-normative; it constrains bindings, not the core).* A binding that exposes a decimal type (for example Python's `Decimal`) and renders it to text before calling the core MUST bound the length of the text it is willing to construct, and MUST reject a value over that bound with `HEPH-MONEY-422` rather than build it: a compact value such as `1E-999999999999` otherwise expands into an unbounded string. A bound rejects values the core would otherwise have handled, and that is no longer limited to values the core would have rounded (for example `1E-999999999` with `half_up`): because fractional digits beyond the exponent are accepted when every one of them is zero, a bound also rejects values the core would have accepted exactly, such as a decimal carrying thousands of trailing fractional zeros. A binding's two entry points therefore disagree beyond the bound — the text form (`Money::parse`) accepts what the decimal form (`from_decimal`) refuses to render — and that is accepted. The Python binding's bound is 4096 characters.

3.7. **Allocation.** Allocating an amount by a list of ratios uses the largest-remainder method. Ratios are non-negative integers (negative ratios are not representable); the list MUST be non-empty and at least one ratio MUST be non-zero, otherwise the call is rejected with `HEPH-MONEY-422`. A negative amount allocates its absolute value and negates each part. For a non-negative amount, each part's exact share is `amount * ratio / sum(ratios)`; take its floor, then distribute the leftover minor units one at a time to the parts with the largest fractional remainders, ties going to the lower index. The parts always sum to the original amount exactly, and every part carries the original currency. For example 100 allocated by `[3,1,2]` is `[50,17,33]`, not `[51,16,33]`.

3.8. **Comparison.** Two amounts of the same currency are ordered by their minor units, compared as signed 64-bit integers: `a` is less than `b` when `a`'s minor units are less than `b`'s, and so on for equal and greater. The three outcomes are named `lt`, `eq` and `gt`; those are the names `conformance/money/compare.json` uses, and every ordering an implementation produces MUST correspond to exactly one of them, whatever that implementation's own spelling (`Ordering::Less`, `-1`, a pair of booleans). The currency's exponent plays no part, because both amounts are already counts of the same minor unit; an implementation MUST NOT compare rendered decimal strings, and MUST NOT convert to a floating-point or decimal type first (3.4). Every pair of amounts of one currency has an ordering: an implementation MUST NOT compute the ordering by subtracting one amount from the other, because the difference of two representable amounts need not itself be representable (`i64::MIN` against `i64::MAX` is a plain "less than", not an overflow).

Comparing two amounts of different currencies MUST fail with `HEPH-MONEY-409`. This holds whatever the amounts are: equal minor units in two currencies are not equal (`JPY 100` against `KWD 100` is a mismatch, not "equal"), and two zeros in different currencies are a mismatch like any other pair, because the operation names two currencies whether or not the values happen to be zero.

Equality is not ordering, and 3.8 does not change it. Two amounts are equal when their minor units and their currencies are both equal; two amounts of different currencies are **unequal**, not an error, so that an amount can be a hash-table key or a set member in languages where an equality test must not fail. An implementation offering ordering as operators therefore has operators of two kinds on one type: equality answers every pair, and ordering rejects a currency mismatch.

An implementation MUST NOT expose ordering through an interface that cannot report the mismatch. In a language whose ordering interface is infallible (Rust's `Ord`, Java's `Comparable`, a C `qsort` comparator), the operation MUST be a separate fallible function (`Money::checked_cmp` in this kit's Rust core) and the infallible interface MUST be left unimplemented, rather than implemented with a fallback ordering on the currency code. A binding whose ordering operators are overloadable (Python's `__lt__` and its three companions) MUST raise the mismatch from them, and MUST treat an operand that is not a monetary value as that language's type error rather than as `HEPH-MONEY-409`: a mismatch says two currencies met, and nothing else may be reported with that code.

This prohibition covers ordering an implementation arrives at without meaning to, not only ordering it chooses to publish. Where a language makes `<` work on an object through an implicit conversion, a monetary value MUST NOT supply that conversion. In JavaScript the hooks are `toString()`, `valueOf()` and `Symbol.toPrimitive`, and **`toString()` is the one that bites**: `a < b` converts each operand with ToPrimitive at hint `number`, and because the default `Object.prototype.valueOf` returns the object rather than a primitive, the conversion falls through to `toString()`. A binding that defines only `toString()` — for display, which is the most natural hook anyone writes — therefore gets `a < b` as a comparison of two *rendered strings*. That breaks this section's own prohibition on comparing rendered decimal strings, and it is wrong in both directions: across currencies `"KES 100" < "USD 50"` is silently true, and within one currency `"USD 9" < "USD 10"` is silently false, the same defect the `lt-jpy-nine-to-ten` vector pins.

A binding that defines `toString()` MUST therefore also define `valueOf()` to throw, rather than leave the inherited default in place, and MUST expose ordering only as named fallible operations. It MAY leave `Symbol.toPrimitive` undefined, which is the smallest shape that works: hint `string` then still reaches `toString()`, so interpolation and `String(money)` keep working, while hint `number` and hint `default` reach the throwing `valueOf()` and the ordering operators fail. Display survives, but not every use of it: binary `+` and loose `==` against a primitive convert at hint `default`, so `"Total: " + money` and `money == 5` throw as well. That is intended rather than incidental, and the alternative is a template literal or an explicit `String(money)`. A binding that does define `Symbol.toPrimitive` MUST make it throw for hints `number` and `default`, and MUST NOT make it throw unconditionally: it is consulted for every hint, `string` included, and it takes precedence over `valueOf()`, so an unconditional throw would both break display and quietly relieve `valueOf()` of the duty this paragraph gives it. A `valueOf()` that returns a number instead of throwing is no better than the default: the comparison then discards the currency, and because a JavaScript number is a double it violates 3.4 as well. The same applies to any other implicit conversion an ordering operator can reach, for example a C++ implicit conversion operator to an arithmetic type.

One accidental ordering is beyond the reach of any hook, and this section cannot close it. `Array.prototype.sort()` with no comparator converts each element with ToString, which reaches `toString()` through hint `string` — the very path the paragraph above preserves for display — so neither the required throwing `valueOf()` nor a conforming `Symbol.toPrimitive` intercepts it, and the result is a lexicographic ordering of rendered strings: wrong across currencies (`KES 100` sorts before `USD 50`) and wrong within one (`USD 10` sorts before `USD 9`). Only the unconditional throw forbidden above would prevent it, and that trade has already been declined, so the hazard is unaddressable here: a binding MUST instead document it and carry a test showing that a default-comparator sort is not relied on for monetary values.

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

5.2. Secrets follow Standard Webhooks: a secret may carry the optional `whsec_` prefix, and the HMAC key is the base64-decoded remainder. Base64 throughout (secret and signature tag) is the standard alphabet and MUST be canonically padded: an unpadded value is rejected, not repaired. The signed content is `<webhook-id>.<webhook-timestamp>.<raw body>`. The signature is HMAC-SHA256 over it, base64-encoded, and `webhook-signature` carries it as `v1,<base64>`. A secret MUST decode to a non-empty key: a secret that is not valid base64 or decodes to zero bytes (an empty string, or `whsec_` alone) is unusable, signing with it fails with `HEPH-VAL-422` (a configuration error, not an authentication outcome), and verifying with it fails with `HEPH-WH-401` (spec 5.6).

5.3. `webhook-signature` MAY hold several space-separated signatures. A message is valid if any signature of a known version verifies. Signatures of unknown versions MUST be ignored, not treated as failures. A `v1` entry whose base64 is malformed or not canonically padded never verifies; it is skipped like any other non-matching entry.

5.4. Verification MUST use constant-time comparison.

5.5. The timestamp tolerance is 300 seconds in either direction, and the boundary is inclusive: a timestamp is accepted when `|now - timestamp| <= 300` and rejected when the difference exceeds 300 (301 seconds old, or 301 seconds in the future, is rejected). A timestamp outside it MUST be rejected even if the signature verifies.

5.6. A failure to verify, for any reason, is `HEPH-WH-401`. The response MUST NOT reveal which check failed.

## 6. Telemetry

**Profiles:** OpenTelemetry semantic conventions.

6.1. Implementations use OpenTelemetry semantic-convention names where one exists. Names in `conventions/attributes.yaml` are the shared names for concepts semantic conventions do not cover, and MUST be used verbatim for those concepts.

6.2. Attributes with `pii: true` MUST be redacted from log output and MUST NOT be sent as metric labels.

6.3. Logs MUST carry `trace_id` (as in 1.6). When an error is returned or recorded, the span MUST carry `heph.error.code`.

## 7. Provenance record

7.1. A provenance record describes one research run. A record MUST carry every member of this table, with the type given, and MUST NOT carry a top-level member this specification does not define. The last column says whether the member belongs to the **determinism contract**: the set of members that decide whether a re-execution is the same run, as against the members that merely describe it.

| Field | Type | Meaning | In the determinism contract |
| --- | --- | --- | --- |
| `run_id` | string | Unique identifier of the run | no, an identifier |
| `config_hash` | string | Content hash (4.2) of the canonical run configuration | yes |
| `data_hash` | string | Content hash (4.2) of the input data, over the digest scope section 10 defines | yes |
| `deps_hash` | string or null | Content hash (4.2) of the dependency lockfile, or `null` when the run had no lockfile | yes |
| `code_sha` | string or null | Git commit SHA of the code that ran, as lowercase hex, or `null` when no git commit names it | yes |
| `class` | string | `deterministic` or `provenance-only` | no, a classification |
| `environment` | object | Descriptive facts about the machine that ran it (7.4) | **no, and never compared (7.2)** |

`deps_hash` is a content hash over the lockfile's bytes exactly as read, not over a parsed or re-serialised form, because the lockfile is not required to be JSON and 4.1 therefore does not apply to it. It is in the determinism contract because two different dependency sets genuinely give different answers, so a replay whose `deps_hash` differs from the record's has not reproduced the recorded run.

The **digest scope** of `data_hash` — whether the hash is taken over raw bytes or over canonical JSON (4.1), and how the inputs of a multi-file dataset combine into one value — is not settled in this section. It is settled with dataset manifests, in section 10, and an implementation follows that section rather than choosing for itself.

This section names code by a **git commit**, and says so plainly rather than inventing an identifier no implementation would use. `code_sha` is the commit that git `HEAD` resolves to, and it is non-null whenever `HEAD` resolves to a commit **regardless of whether the working tree is clean**: a dirty tree does not make `code_sha` `null`, it costs the run the `deterministic` class instead (7.3). `code_sha` is therefore `null` exactly when `HEAD` resolves to no commit, which covers every case that yields no commit SHA: code under no version control at all, a git repository with no commit yet, and a tree held in another version-control system. Where `HEAD` resolves, the record MUST carry that SHA; omitting the member is never an alternative to the `null`. A `null` means nothing in the record names the code that produced the result, so the run is `provenance-only` (7.3).

`run_id` is opaque: implementations MUST NOT derive meaning from its form. Two records that differ only in `run_id` describe the same re-execution.

Where a record is hashed, the hash is a content hash (4.2) over the record's canonical JSON (4.1).

7.2. `class` MUST be exactly `deterministic` or `provenance-only`. The hyphen in `provenance-only` is normative; `provenance_only` is not a value of this field.

A `deterministic` run re-executes from the members of its determinism contract to an identical result. A `provenance-only` run records how a result was produced and makes no claim that re-executing it reproduces the result exactly. Both classes carry the same members: `provenance-only` is a weaker claim, not a record with members left out, though `code_sha` or `deps_hash` may be `null` in one (7.1, 7.3).

Whatever else a replay compares, it MUST NOT compare `environment`, and a record that differs from another only in `environment` MUST NOT be reported as a divergence. This is what makes `deterministic` a wearable label: the same configuration, data, dependencies and code re-executed on a second machine is the same run even though its platform, runtime version and accelerator differ, and a contract that said otherwise would be satisfiable by no two machines.

7.3. A run MUST be classified `provenance-only`, never `deterministic`, unless **all** of these hold when the run starts:

- **A git commit names the code**, that is `HEAD` resolves and `code_sha` is non-null (7.1). Otherwise `code_sha` is `null`, and a record that does not name the code that produced the result cannot claim that the code re-executes to it.
- **The working tree is clean.** Nothing tracked in the commit named by `code_sha` differs from it, and no untracked file is present other than those the repository's own ignore rules exclude. A tree for which `git status --porcelain` prints nothing satisfies this. Without the condition `code_sha` stops identifying the code that produced the result, which is the one thing it is in the record to do.
- **A dependency lockfile exists.** Otherwise `deps_hash` is `null`, the dependency set is unpinned, and nothing in the record pins the versions that produced the result.

A record whose `class` is `deterministic` therefore MUST carry a non-null `code_sha` and a non-null `deps_hash`. An implementation MAY impose further conditions of its own before it classifies a run `deterministic`, and MUST NOT classify a run `deterministic` when any condition above fails. A run that fails one is still recorded in full: it carries `config_hash`, `data_hash`, `environment` and whichever of `code_sha` and `deps_hash` it can, so a run whose code no git commit names is recorded and classified rather than refused, and loses no traceability by being honest about its class.

7.4. `environment` MUST be present and MUST be an object. It is descriptive: it records what the run met, so that a reader of a published result can see it, and it takes no part in any comparison (7.2). Its members:

| Member | Type | Meaning | Example |
| --- | --- | --- | --- |
| `platform` | string | Operating system and architecture | `macOS-15.6-arm64` |
| `python` | string | Version of the Python runtime the run executed under | `3.12.7` |
| `frameworks` | object | Library name to version string, or `null` for a library that was looked for and not found | `{"numpy": "2.1.3", "torch": null}` |
| `accelerator` | object or null | `{"model": string, "driver": string}`, or `null` when the run used no accelerator | `{"model": "NVIDIA RTX 4090", "driver": "550.54.14"}` |

A `null` under `frameworks` means the library was looked for and was absent; a library the implementation never looked for is simply not a member. Absence is recorded, not assumed.

These members are individually optional, because an implementation records only what it can observe, but their names and types are reserved: an implementation that records one of these facts MUST use the name and type given here and MUST NOT record the same fact under another name. An implementation whose runtime is not Python omits `python` and records its own runtime version under a member named for that runtime, such as `go`. Further members MAY be added, subject to 7.5.

7.5. `environment` MUST NOT carry the hostname of the machine, the name of the user who ran it, or any filesystem path, under those or any other member names. A record is committed and published alongside the result it describes, and those three identify a person or a machine instead of describing an environment; 6.2 already requires `pii: true` attributes to be redacted from log output, and a record outlives a log line. A project that needs them keeps them in its own configuration, outside the record.

## 8. Run records

8.1. A **run record** is the account of one research run: the provenance record of section 7, the rows the run produced, and a summary derived from those rows. A reported number MUST come from a row of a record. This section exists so that "a number cannot exist without a record" is a property of the artefact rather than a habit of whoever ran it.

A record is a **directory**. The names of the three files in it are normative:

| File | Holds | Written |
| --- | --- | --- |
| `provenance.json` | The section 7 provenance record of the run, as one JSON object | Once, before the first row (8.3) |
| `rows.jsonl` | The rows, one per line, in completion order (8.2) | Appended as each cell completes (8.3) |
| `summary.json` | The summary derived from the rows (8.4) | Once, when the run finishes (8.4) |

Every document in a record is canonical JSON (4.1), so the record of one run is the same bytes wherever it is written and a hash over one of its files depends on what the file says rather than on how it was formatted. A file holding one document — `provenance.json`, `summary.json` — holds exactly that document's canonical JSON and nothing after it, not even a trailing newline, so that the hash of the file is the content hash of the document. `rows.jsonl` is JSON Lines: each line is one canonical JSON object followed by a single LF (U+000A) and holds nothing else, so a reader may read a record a line at a time and a writer may append to it without rewriting what is already there.

`provenance.json` holds the section 7 record **unchanged**. 7.1 forbids a record to carry a top-level member that specification does not define, so what this section needs and section 7 does not name — the rows, the summary — lives in a document of its own and never as an eighth member of the provenance record.

A record carries **no wall-clock time**, under any member name, in any of its three documents. Section 7 defines none and this section adds none, for a reason that outlives both: a replay (section 9) compares a record's rows against the rows of a re-execution, so a clock reading recorded in a compared position would make every replay of even a perfectly reproducible run diverge. A project that needs to know when a run happened reads it from the commit that carries the record, which is where the question is answered without putting the answer somewhere a comparison has to ignore.

8.2. A **row** is the result of one **cell**: the smallest unit of work the run completes and can be reported on, such as one model against one dataset. A row document carries exactly these two members and MUST NOT carry another:

| Member | Type | Meaning |
| --- | --- | --- |
| `cell` | string | Name of the cell that completed. Non-empty, and unique within the record |
| `values` | object | The values that cell produced, by name. MAY be empty |

Each member of `values` is a JSON string, a finite JSON number, or the object `{"nonfinite": t}`, which carries exactly the member `nonfinite` and MUST NOT carry another, where `t` is exactly one of `"NaN"`, `"Infinity"` and `"-Infinity"`. An object that is not that is not a value this section defines, and a reader MUST refuse it rather than read it as something else. A reader MUST read that object back as the value it names, and MUST NOT treat it as an ordinary object. The wrapper exists because research results do contain non-finite values and JSON cannot carry one: 4.3 rejects them outright, and the bare tokens `NaN` and `Infinity` that some encoders emit are not JSON and are rejected by a conforming parser in another language. Recording a diverged loss as a thing every reader can parse is what the wrapper buys; writing those bare tokens into a record is forbidden, and so is dropping the value or substituting a finite one for it.

A cell name MUST be unique within a record. A record that named one cell twice could not say which of the two values the run produced, so an implementation MUST refuse a second row for a cell it has already recorded rather than appending it, overwriting it or keeping the last.

8.3. **Incremental write semantics.** A record is written as the run proceeds, never assembled at its end.

- `provenance.json` MUST be written and MUST be durable before the first row is appended. A directory holding rows and no provenance record describes a run nothing identifies.
- `rows.jsonl` MUST exist, possibly empty, from the moment the record is open, so that a run which died before its first cell is still the record of a run that started.
- Each row MUST be appended as one line, and MUST be **durable before the call that appended it returns**. Durable means handed to storage rather than left in a buffer the writing process owns: the bytes MUST survive the death of that process without a further call. A write followed by a flush of the application buffer and a synchronisation of the file to its storage satisfies this; a write into a buffer flushed at some later convenient moment does not.
- A record MUST NOT be rewritten. A row once written is never amended or removed, and `summary.json` is written once.

A reader MUST treat a final line of `rows.jsonl` that is not terminated by LF as the row that was in flight when the writer died, and MUST discard it: a line without its LF was never a complete row, and that one row is what the paragraph below permits a crash to cost. Every LF-terminated line MUST be a row document (8.2), and a reader that meets one which is not MUST refuse the record rather than skip the line — such a file has been corrupted or edited, and reading past it would report a run whose rows nobody can account for. A reader MUST NOT apply the first rule to any line but the last.

The cost of a crash is therefore at most the row in flight: every cell that completed before it is on disk and readable. That is the whole point of writing a record this way, and the reason it is a MUST rather than a quality of implementation — a run that buffers its rows and dies loses the work of every cell it had finished.

8.4. The **summary** document carries exactly these three members and MUST NOT carry another:

| Member | Type | Meaning |
| --- | --- | --- |
| `run_id` | string | The `run_id` of this record's provenance record (7.1) |
| `cells` | array of strings | Every cell name, in the order the rows give them |
| `rows` | integer | The number of rows in `rows.jsonl` |

Every member is derived from the record's other two documents. The summary is an **index**, not a second place where results live: a number exists in a row or it does not exist, and an implementation MUST NOT record in the summary a value no row holds.

A reader MUST recompute the summary from the rows, and MUST refuse a record whose stored `summary.json` disagrees with what the rows say. Such a directory is not a run record: reporting from it would be reporting what the rows do not hold, which is the one thing a record exists to prevent.

A run that ends by failing has not finished: an implementation MUST NOT write a summary for it, so a run whose experiment raised leaves its rows and no summary, exactly as a killed one does.

A record holding no `summary.json` is **unfinished**: the run did not reach its end. A reader MUST still read its rows and MUST NOT refuse it for the missing summary, since the rows of an unfinished record are exactly what 8.3 was written to preserve. A reader MUST be able to tell an unfinished record from a finished one, and MUST NOT present an unfinished one as a complete run.

8.5. **A record that cannot be written is a failed run, not a quiet one.** Every failure to create the record directory, to write or synchronise the provenance record, to append a row, or to write the summary MUST be raised to the caller and MUST fail the run.

An implementation MUST NOT, on such a failure: warn and continue; log it and return a result; write the record to any location other than the one it was given; skip, buffer or drop a row; or report a number the record does not hold. A run whose record failed produced no citable number, whatever else it computed. An unwritable record is the failure mode this clause is aimed at, because it is the one an implementation is most tempted to be helpful about.

8.6. An implementation MAY offer a **registry of experiments**, and one that does MUST shape it so that an experiment cannot choose where its results go. An experiment is a function of one argument, the open record. It MUST NOT be passed a directory, a path or any other destination, and an implementation MUST refuse at registration a function that takes one rather than discovering the problem when the function runs. Opening the record, choosing where it goes and closing it belong to the runner.

This is what 8.1 rests on: no destination reaches an experiment through its signature, so the record it was handed is the only one it was given. The rule is about what an implementation passes, and it is deliberately not a claim that an experiment cannot write a file by other means — nothing in a general-purpose language could enforce that, and a section that pretended otherwise would be describing a guarantee no implementation can keep.

## 9. Replay and diff

9.1. A **replay** re-executes the run that a record (section 8) describes and compares the result against that record. Its product is a **difference report** (9.2). A replay that differs is not a failure of the tool: it names which values moved, and that naming is the finding. An implementation MUST produce the report, and MUST NOT refuse in place of producing one.

A replay compares exactly two things:

- **The determinism contract of the record's provenance record**: `config_hash`, `data_hash`, `deps_hash` and `code_sha` (7.1). These are the members that decide whether a re-execution is the same run. A replay whose values for them differ from the record's has not re-executed the recorded run; it has run against different configuration, different data, different dependencies or different code, and the report says which rather than leaving the reader to infer it from a differing result.
- **The rows** (8.2), by cell name and, within a cell, by value name.

It compares nothing else. Each of the three members of 7.1 that is not in the determinism contract is excluded for a reason of its own:

- `environment` MUST NOT be compared, and two records differing only in `environment` MUST NOT be reported as a divergence. 7.2 requires this and says why: a contract that compared the platform, the runtime version and the accelerator would be satisfiable by no two machines.
- `run_id` MUST NOT be compared. 7.1 makes it opaque and says that two records differing only in `run_id` describe the same re-execution; a replay is a new run with a new identifier, so comparing it would make every replay of every run diverge.
- `class` MUST NOT be compared. It classifies how a run was made rather than what it produced, and the same commit replayed from a tree that has since been edited is classified `provenance-only` while reproducing the record's rows exactly. The report says whether the run reproduced; the recorded `class` says what the record claimed, and a reader weighs the two together, since a `provenance-only` run never promised a match (7.2).

A replay does not compare `summary.json`. Every member of the summary is derived from the rows (8.4), and a reader has already refused a record whose stored summary disagrees with them, so comparing it would compare the rows a second time under another name.

The **order of the rows is not compared**. 8.2 writes the rows in completion order, which is not a result: a run whose cells complete concurrently does not fix it, and a replay that called a reordering a divergence would report one against a run that reproduced every value it holds. Cells are matched by name, which 8.2 makes unique within a record.

This section does not define how a run's external inputs are made available to a re-execution; freezing them is settled in a later version of this specification. A replay re-executes the experiment (8.6) and compares what this section says to compare. A replay whose inputs were not frozen and that matches is evidence that the experiment reproduced under the inputs the replay met; what carries the identity of those inputs is `data_hash`, which is compared like every other member of the determinism contract.

9.2. A **difference report** carries whether the replay matched and the differences it found. A report **matched** if and only if it carries no difference: an implementation MUST NOT report a match alongside a difference, nor a divergence with none.

Each **difference** names one **position** and the two values found there:

| Member | Meaning |
| --- | --- |
| `cell` | Name of the cell the position is in, or `null` when the position is a member of the determinism contract |
| `key` | Name of the value within that cell, or the name of the determinism-contract member when `cell` is `null` |
| `recorded` | The value the record holds at that position, or `null` when it holds none |
| `replayed` | The value the re-execution produced at that position, or `null` when it produced none |

The positions compared are the four determinism-contract members and every `(cell, key)` pair that either side's rows hold. A position both sides hold, whose values differ under 9.3, is one difference carrying both values. A position only one side holds is one difference carrying that side's value with `null` on the other: a row value is never `null` (8.2), so a `null` at a row position says the position is absent rather than that the value recorded there was null.

Both sides always hold all four determinism-contract positions, since 7.1 requires every record to carry every member. A `null` at one of those four is therefore the member's **value**, which 7.1 permits for `deps_hash` and for `code_sha`, and never an absence: a difference reading `deps_hash`, a hash, `null` says the re-execution had no lockfile.

A cell only one side holds therefore appears as one difference per value it holds, which names every value that is unaccounted for. A cell holding no values — 8.2 permits an empty `values` — has no `(cell, key)` position at all, and MUST still be reported: it is one difference naming the cell, with `key`, `recorded` and `replayed` all `null`. A difference whose `recorded` and `replayed` are both `null` is exactly that case and no other.

The differences are **ordered**, so that one replay reported twice reads the same way: the determinism-contract members first, in the order of 7.1's table; then the positions of the record's rows, in the order the rows and each row's `values` give them; then the positions only the re-execution holds, in the order its own rows give them.

A report says which values moved and no more. An implementation MUST NOT put a conclusion in it — a ranking, a cause, a verdict on whether the run is flaky — because the report is read by someone deciding exactly that, and the values are what they need.

9.3. Two values at a position are compared **by kind first**. A string, a finite number and a non-finite value (8.2) are three kinds, and two values of different kinds differ whatever they look like: the string `"1.0"` and the number `1.0` are a difference, and so are `NaN` and any number.

- Two **strings** are equal if and only if they are the same sequence of code points. Nothing is normalised, trimmed or case-folded.
- Two **non-finite values** are compared **by the value their wrapper names** (8.2). `{"nonfinite": "NaN"}` is therefore **equal to** `{"nonfinite": "NaN"}`, so **`NaN` compares equal to `NaN` for the purposes of a replay**, which is what IEEE 754 equality does not do. `Infinity` equals `Infinity`, `-Infinity` equals `-Infinity`, and `Infinity` and `-Infinity` differ. 8.2 carries a non-finite value so that a diverged loss can be recorded; a record exists to be compared against, and a value that did not compare equal to itself would make a replay report a difference between a run and that same run. This is the one comparison an implementation is all but guaranteed to get wrong by reaching for its language's `==`.
- Two **finite numbers** are equal within the tolerance below, and only within it.

**The float tolerance.** Two finite numbers `a` and `b` are equal if and only if

```
|a - b| <= max(1e-9 * max(|a|, |b|), 1e-12)
```

The tolerance is **both relative and absolute**, and the formula is symmetric in `a` and `b`, so a comparison does not depend on which side of it the record is.

- The **relative** part, `1e-9`, is what makes 7.2's contract satisfiable. Binary64 carries about 15.95 decimal digits, so `1e-9` is roughly seven orders of magnitude looser than the representation: it absorbs the reassociation that a different BLAS, a different thread count or a fused multiply-add introduces across a long reduction, which is exactly the difference 7.2 says a second machine may have while running the same run. It is at the same time far tighter than the precision a result is reported to; a number quoted to four significant figures cannot hide a change beneath `1e-9`, so the tolerance never conceals a moved value a reader would otherwise have seen.
- The **absolute** part, `1e-12`, is there because a relative comparison is useless near zero. `0.0` against `1e-300` is an infinite relative error, so a loss that reached zero in one run and a denormal in the next would diverge forever. `1e-12` is below the precision of any number a result is reported to and above the scale at which a difference is arithmetic noise rather than a finding.
- The two combine with `max`, so a pair is equal if it passes on either. Where both values are zero the relative part is zero and the absolute part decides; `0.0` and `-0.0` are equal, their difference being zero.

An implementation MUST NOT loosen this tolerance per run, per cell or per value, and MUST NOT offer a mode in which a pair this clause calls different is reported as a match. A quantity whose reproduction needs a looser comparison than this is not a quantity a replay can speak about, and an experiment that produces one records alongside it something that can be.

9.4. **What a match means, and what it does not.** Two things section 7 leaves open are discovered by a replay rather than by reading a record. They are named here rather than left silent, because a replay is the operation that meets them.

First, **a record does not witness its own cleanliness.** 7.3's conditions hold *when the run starts*, and none of the seven members of 7.1 records that the working tree was clean, so a reader of a record cannot check that `deterministic` was assigned honestly. This is deliberate rather than an omission. A member saying "the tree was clean" would be one more self-assertion by the same implementation, with exactly the standing of the `class` it would be vouching for; a record cannot witness its own honesty. What tests the claim is a replay, which re-executes and compares, so that its report is evidence about the world rather than a restatement of what the record says about itself. An implementation MUST NOT present a recorded `deterministic` as a verified fact. A replay that matched is the nearest thing to one.

Second, **a run that starts clean and is edited while it runs still qualifies.** 7.3 is checked when the run starts, so such a run is classified `deterministic` while its `code_sha` names a commit that is not the code that finished it. A replay is what finds this: all four determinism-contract members can match — the commit is the same, the lockfile is the same — while the rows differ, and a report of exactly that shape is the signature of a tree edited mid-run. An implementation MAY re-check the tree when a run ends. One that does MUST NOT rewrite the record's `class`, since 8.3 forbids rewriting a record, and records what it found as a run of its own rather than as an amendment to one that has finished.

A **caller that needs a refusal** rather than a report — a continuous-integration gate asking whether a cited run still reproduces — derives it from the report, and `HEPH-LAB-409` is the registry code for it. That is a decision about what to do with a finding, and this section's requirement that a replay produce the report stands either way.

## 10. Dataset manifests

**Reserved. This section is not yet specified.**

The digest scope of `data_hash` (7.1) — whether the hash is taken over raw bytes or over canonical JSON (4.1), and how the inputs of a multi-file dataset combine into one value — is settled here, together with the manifest a dataset carries.

Until this section is written, an implementation records the `data_hash` it is given and MUST NOT choose a digest scope of its own (7.1).
