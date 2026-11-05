# 0016. Accept value-preserving trailing zeros in decimal money input

## Status

Accepted. Date: 2026-11-05. Supersedes the trailing-zero sentence of spec 3.6, which read that the rule is about the digit count as written and that KES `10.290` is rejected.

## Context

Spec 3.6 decided excess fractional precision on the digit count as written, so `reject` refused any input with more fractional digits than the currency's exponent, trailing zeros included. The Collie phase gate showed what that costs: `Money.from_decimal(Decimal("5000.00"), "JPY")` raised `HEPH-MONEY-422` even though the value is exactly 5000 and nothing is lost. Postgres hands back scale-2 decimals from a `NUMERIC(12,2)` column, the standard SQL shape for a money column, so every 0-exponent currency (JPY, UGX, KRW, ISK, XOF) was unreachable for any consumer storing money that way. Worse, the genuinely lossy `Decimal("5000.50")` for JPY raised the identical error, so the implementation could not distinguish digits it may drop without changing the value from digits that carry value. The counting rule was chosen because it is trivially explainable and never surprises a caller with a silent change of value; the gate showed that the surprise it actually produces is a rejection of a value that round-trips exactly.

## Decision

Fractional digits beyond the currency's exponent are accepted when every one of those digits is zero, because the value is preserved exactly: KES `10.290` is 1029 minor units, JPY `5000.00` is 5000, BHD `1.2340` is 1234, and JPY `-0.00` is 0. A non-zero digit beyond the exponent is still rejected with `HEPH-MONEY-422` unless the caller supplies an explicit rounding mode, so rounding keeps meaning actual rounding and no value is ever discarded silently. A rounding mode applied to input whose excess digits are all zero yields the same minor units as `reject` does. The public signatures of `Money::parse`, `Money::from_decimal` and `Rounding` do not change, and no new error code is introduced.

## Consequences

Money becomes usable against `NUMERIC(n,2)` columns for every currency, which unblocks Phase 1 for 0-exponent currencies. The accepted set of inputs grows and never shrinks: nothing that parsed before is rejected now, and no accepted input changes its minor units, so the change is additive for any existing caller. The trade-off is that the rule now depends on the digit values rather than on the digit count, so "how many fractional digits may I write" is no longer the whole answer and the spec, the vectors and the bindings' documentation must all state the value rule instead. `HEPH-MONEY-422` from a decimal parse now means precision would actually be lost, which makes the error message more honest but changes what a caller may infer from it. Collie's `test_scale_2_amounts_work_for_zero_exponent_currencies` is an `xfail(strict=True)` asserting this behaviour, so it flips to XPASS and fails Collie's suite until that project is updated; that is the intended signal and belongs to a separate Collie change.
