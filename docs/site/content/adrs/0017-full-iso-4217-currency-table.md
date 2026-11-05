---
# GENERATED FILE - do not edit by hand. Source: docs/adr/0017-full-iso-4217-currency-table.md.
# Regenerate with `uv run tools/gen_site_pages.py`; CI runs --check.
title: "0017. Generate the full ISO 4217 currency table, funds codes included"
---

# 0017. Generate the full ISO 4217 currency table, funds codes included

## Status

Accepted. Date: 2026-11-05. Supersedes the sentence of spec 3.3 that named `conformance/money/currency.json` the normative exponent table "for the currencies Phase 1 supports"; the normative registry is now `spec/currencies.yaml` and the vector file pins a sample of it.

## Context

The core's exponent table held 19 codes, written out by hand. The Collie phase gate showed what that costs: Collie already renders GHS, INR, CAD, AUD and BRL in its PDF service and stores `invoice_currency` as a bare `String(3)`, so a code outside the 19 reached `Money` at runtime and raised `HEPH-MONEY-422` for a currency that ISO 4217 defines perfectly well. Adding codes on demand turns the table into a queue of requests, and the next ingot hits the same wall with a different five codes. The table is also hand-maintained data about an external standard, which is the shape of data this repo generates rather than types out: nothing checked that any of the 19 exponents still matched what SIX Group publishes.

ISO 4217 List One, the standard's current currency and funds code list, carries 178 distinct alphabetic codes in the publication retrieved for this change. 165 of them have a numeric minor-unit field; 13 publish the field as `N.A.` because no exponent is defined for them (`XXX`, `XAU`, `XAG`, `XPT`, `XPD`, `XDR`, `XTS`, `XSU`, `XUA` and the four Bond Markets Unit codes). Spec 3.3 already required that the `N.A.` codes be rejected, so the question this decision settles is not whether to reject them but where the boundary is drawn and by whom.

Nine of the numeric codes are **funds codes**: `CHE`, `CHW`, `USN`, `MXV`, `COU`, `BOV`, `CLF`, `UYI` and `UYW`. They denote units of account and next-day settlement values rather than circulating money, and a reader could reasonably expect a money library to refuse them.

## Decision

The accepted currency set is the whole of ISO 4217 List One, decided by one mechanical rule: **a code is accepted if and only if List One gives it a numeric minor-unit field, and its exponent is that field.** `spec/currencies.yaml` transcribes List One in full, keeping the `N.A.` entries so the rule is applied by code rather than at transcription time, and records the publication it came from (URL, the XML's `Pblshd` date, the retrieval date, and the amendment number). `tools/gen_currencies.py` renders `core/hephkit-core/src/money/currency_table.rs` from it and fails under `--check` if the committed output drifts; that generated file is the only place the table lives, and it is never edited by hand. The registry is updated by re-transcribing a newer List One in full, never by editing one code's exponent, because a single hand-edited number is a claim about the standard that nothing checks.

**The funds codes are accepted.** Three reasons, in the order that decided it. First, List One as published does not distinguish them: there is no field in the XML, and no marker in the entry, that separates a funds code from a circulating currency. Excluding them therefore means carrying a hand-written list of nine codes that is not derivable from the source — reintroducing, at a smaller scale, exactly the hand-maintained exception this change removes, and introducing a second, unchecked claim about the standard. Second, `CLF` is a funds code and was already one of the 19 codes the core accepted, so excluding funds codes would make a currency that works today stop working, or else require `CLF` as a carve-out from the carve-out. Third, the rule is well-defined for them on its own terms: a funds code has a published exponent, so counting its minor units, parsing a decimal into them and formatting them back are all exactly as meaningful as for `USD`. Whether a given product should let a customer be invoiced in `USN` is a question about that product's currency allow-list, which belongs at the product's own boundary; the core holds no policy, does no I/O and should not be the place that opinion is encoded. We did not find a reason the mechanical rule is wrong for the funds codes, and we deliberately did not deviate from it.

`Currency`, `Currency::from_code`, `Money`'s public API and `HEPH-MONEY-422` are unchanged. The 19 codes accepted before this change are a strict subset of the 165 accepted after it, with identical exponents, verified code by code against the publication.

## Consequences

Any ISO 4217 currency with a published exponent now works, so an ingot never waits on hephkit to add a code; Collie's five codes work without a hephkit change, and `Currency` stops being a bottleneck. The exponents become auditable: the registry names its source, the generator is the only writer, and `--check` catches drift, so an exponent can no longer be wrong in a way nobody notices.

The cost is that the accepted set now tracks an external publication on the standard's schedule rather than ours. A code the standard retires from List One stops being accepted the next time the registry is re-transcribed, which is a real behaviour change delivered by a data update, so re-transcription is a spec version bump and a vectors change like any other. Today that boundary already bites: `BGN` moved to the historical list under Amendment 180 when Bulgaria adopted the euro, so the lev is rejected even though amounts denominated in it exist in the world. Nothing regresses — `BGN` was not among the 19 either — but an ingot holding historical amounts in a retired code cannot represent them, and a future decision to accept List Three would be a separate ADR, not a quiet widening of this rule.

Accepting 165 codes also means a typo can now land on a real currency: `USN` for `USD`, or `CHE` for `CHF`, is validated rather than refused. That is the price of not encoding policy in the core, and the mitigation belongs where the policy does — a product that invoices in four currencies should validate against those four, not rely on `Currency` to be narrow. `TWD` is in List One and so is accepted, which is a code some jurisdictions treat as politically sensitive; the core follows the standard and takes no position.

Funds codes being accepted is the part a future reader is most likely to question, which is why the reasoning above is recorded rather than the outcome alone. If it is ever revisited, the thing to change is the rule in `tools/gen_currencies.py` and this ADR, not the generated table.
