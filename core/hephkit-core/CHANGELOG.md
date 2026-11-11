# Changelog

## [0.2.0](https://github.com/Neoforge-Labs/hephaestus/compare/hephkit-core-v0.1.0...hephkit-core-v0.2.0) (2026-11-11)


### ⚠ BREAKING CHANGES

* **money:** the set of currency codes Money accepts grows from 19 to the 165 ISO 4217 codes with a published minor-unit exponent. Nothing accepted before is rejected now and no exponent moved, but a caller that relied on a code outside the 19 being refused will see it accepted.
* **money:** inputs with value-preserving trailing fractional zeros now parse under Rounding::Reject instead of returning HEPH-MONEY-422.

### Features

* **core:** money with currency exponents, strict parsing and allocation ([0c6b80a](https://github.com/Neoforge-Labs/hephaestus/commit/0c6b80acfd675c7fd76457fd21eefb75d31d024a))
* **core:** RFC 8785 canonical JSON, content hashes and UUIDv7 ([db8b24a](https://github.com/Neoforge-Labs/hephaestus/commit/db8b24aff8ed9a0a97a452308a3b34111834e932))
* **core:** Standard Webhooks signing and verification ([4e15bc3](https://github.com/Neoforge-Labs/hephaestus/commit/4e15bc365eeeed5e657d378b0d8228054afbfacd))
* **core:** wire-format money parsing in the core; pin excess-zero rejection in spec 3.6 ([4fa8bfd](https://github.com/Neoforge-Labs/hephaestus/commit/4fa8bfd08f33d97eb63097c7def86a2f0b2bef60))
* **docs:** the Hephaestus docs site, generated from the spec ([932e942](https://github.com/Neoforge-Labs/hephaestus/commit/932e9421cfe9a95c6e0560ccff0110f9f0b74a50))
* **money:** accept value-preserving trailing zeros ([2da969a](https://github.com/Neoforge-Labs/hephaestus/commit/2da969af74f6d7133f40a9448e3246eb09bbb4d3))
* **money:** compare amounts of the same currency ([5269fc8](https://github.com/Neoforge-Labs/hephaestus/commit/5269fc84b89494b9a142b16b297382a40b22bace))
* **money:** generate the full ISO 4217 currency table ([cab7abc](https://github.com/Neoforge-Labs/hephaestus/commit/cab7abcf5ffdbc548db7fb5f0f8c3fbd3d772d92))
* **tools:** enforce in-source Maturity labels for rust, python and go modules ([d1c8460](https://github.com/Neoforge-Labs/hephaestus/commit/d1c84608d1757a6e8697dabafd5be2e1d01ec3c0))


### Bug Fixes

* **core:** bound the tie check, carry the duplicate-key money vector as text, drop serde_json from normal deps ([4213c1f](https://github.com/Neoforge-Labs/hephaestus/commit/4213c1f54179a4036be19ebda30151813e3a4e63))
* **core:** document error variant mapping and base64 padding, stream signature candidates ([b9e495b](https://github.com/Neoforge-Labs/hephaestus/commit/b9e495bbec95e32077c094171b23313962faaeb1))
* **core:** reject unusable webhook secrets, pin literal timestamp text, test error Display ([13f0597](https://github.com/Neoforge-Labs/hephaestus/commit/13f059760f598db8f42d31b448d0c8bff98f25bc))
* **money:** make the rejection message name the value, not the digit count ([aed33d9](https://github.com/Neoforge-Labs/hephaestus/commit/aed33d959cdd82b8d4cbce793a8c6a6cd91ef378))
* **money:** narrow 3.8's Symbol.toPrimitive requirement, and stop the guard going blind on a quote char literal ([32b1d9c](https://github.com/Neoforge-Labs/hephaestus/commit/32b1d9c3742eff4f79cc4bf213f0d00516c6102d))
* **money:** pin the ISO 4217 publication by hash and make the registry re-derivable ([e3c4ee8](https://github.com/Neoforge-Labs/hephaestus/commit/e3c4ee8c8f2b5c29f5a30f2a78c21e0ff3659df5))
