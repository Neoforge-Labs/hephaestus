# Changelog

## [0.2.0](https://github.com/Neoforge-Labs/hephaestus/compare/hephkit-v0.1.0...hephkit-v0.2.0) (2026-11-11)


### ⚠ BREAKING CHANGES

* move the public host to hephkit.dev
* **money:** inputs with value-preserving trailing fractional zeros now parse under Rounding::Reject instead of returning HEPH-MONEY-422.

### Features

* **docs:** the Hephaestus docs site, generated from the spec ([932e942](https://github.com/Neoforge-Labs/hephaestus/commit/932e9421cfe9a95c6e0560ccff0110f9f0b74a50))
* **money:** accept value-preserving trailing zeros ([2da969a](https://github.com/Neoforge-Labs/hephaestus/commit/2da969af74f6d7133f40a9448e3246eb09bbb4d3))
* **money:** compare amounts of the same currency ([5269fc8](https://github.com/Neoforge-Labs/hephaestus/commit/5269fc84b89494b9a142b16b297382a40b22bace))
* move the public host to hephkit.dev ([9362082](https://github.com/Neoforge-Labs/hephaestus/commit/9362082e4f7c63e74926c1e10bdb4d504956cacb))
* **python:** fail-fast settings with prod-required secrets ([592548d](https://github.com/Neoforge-Labs/hephaestus/commit/592548db9ddc30a62966756284b594468900d7b3))
* **python:** hephkit money, hashing and signatures over the Rust core ([c552dd1](https://github.com/Neoforge-Labs/hephaestus/commit/c552dd1f668062861a6b0b9e2c18dc8e22e983b6))
* **python:** one-call OpenTelemetry and structured logging with redaction ([f5f05d5](https://github.com/Neoforge-Labs/hephaestus/commit/f5f05d5f10d08c591ba2058ad7ea351b9a0068bb))
* **python:** problem+json errors generated from the registry ([f1da19f](https://github.com/Neoforge-Labs/hephaestus/commit/f1da19f9de6af284932c7c8f403febf7a4ad1ae9))
* **tools:** enforce in-source Maturity labels for rust, python and go modules ([d1c8460](https://github.com/Neoforge-Labs/hephaestus/commit/d1c84608d1757a6e8697dabafd5be2e1d01ec3c0))


### Bug Fixes

* **errors:** use the generated codes, and stop a caller fabricating a trace_id ([f37624b](https://github.com/Neoforge-Labs/hephaestus/commit/f37624b9a3e301084e82525fc69d89c88c49071d))
* **observability:** bound the probe, keep prod exporting, accept a lowercase level ([5ea2dfa](https://github.com/Neoforge-Labs/hephaestus/commit/5ea2dfaff480d08b4127d549773c76de2cb9128a))
* **observability:** make logging opt-in, register shutdown, reject a bad level ([ef7ad7b](https://github.com/Neoforge-Labs/hephaestus/commit/ef7ad7b9b114031194584f7b3772eda0f7a7d6fc))
* **python:** case-insensitive webhook headers, legible Decimal size cap, specific 64-bit range errors ([27717cf](https://github.com/Neoforge-Labs/hephaestus/commit/27717cf71cb850e81e7bc7f83634ca07ffcec693))
* **python:** close key-repr, memoryview and oversized-int paths in log rendering ([7632548](https://github.com/Neoforge-Labs/hephaestus/commit/7632548b8832bbcf618fcc183c04aab4fb5fb36b))
* **python:** default problem detail to the registry hint, optional OpenTelemetry, problem+json 404 ([fad02f8](https://github.com/Neoforge-Labs/hephaestus/commit/fad02f8b26efc8691657781df1b8bd73b8f6dddd))
* **python:** dispatch coded exceptions without re-raise, consumer-facing detail hints ([61327d7](https://github.com/Neoforge-Labs/hephaestus/commit/61327d71f0171da46c596793edac37a99f32b3a9))
* **python:** fail closed on colliding header names, reject bool ratios, accurate 64-bit overflow errors ([99f7e80](https://github.com/Neoforge-Labs/hephaestus/commit/99f7e80b5834619f57a21b829d74329899466bb4))
* **python:** keep nested mappings intact when a key's str raises ([9a4fe63](https://github.com/Neoforge-Labs/hephaestus/commit/9a4fe63f06202e4418310592000e066ac442e3b4))
* **python:** match and emit dict keys from the data the JSON serialiser writes ([e4a67a7](https://github.com/Neoforge-Labs/hephaestus/commit/e4a67a77d479f5bd32968cd05d3a098678dd0404))
* **python:** never render secrets through reprs or containers, tolerate non-JSON keys ([bf6eba2](https://github.com/Neoforge-Labs/hephaestus/commit/bf6eba264802babf53231ff4ae32be51f9bdf1db))
* **python:** report pydantic-required and prod-required settings together, surface typo'd env vars ([6e81d34](https://github.com/Neoforge-Labs/hephaestus/commit/6e81d340a727062e82b30a34df90114808ceea28))
* **python:** survive unserialisable extensions of any depth, tighten 429 and 500 hints ([40936dc](https://github.com/Neoforge-Labs/hephaestus/commit/40936dc2206246f787d3b9329416fb3f0d4ccd6d))
* **python:** word-boundary redaction with caller keys, bounded shutdown, restartable tracer ([abfa63a](https://github.com/Neoforge-Labs/hephaestus/commit/abfa63a1b8a9207bdc93419c820862a96e7e0005))
* **release:** unblock the release — PAT-authored PR, and stay inside 0.x ([8eb5ca5](https://github.com/Neoforge-Labs/hephaestus/commit/8eb5ca504bdbc5e41c73288e02d447d31cd98da8))
* **tests:** stop three redaction sentinels colliding with the log line ([922f92c](https://github.com/Neoforge-Labs/hephaestus/commit/922f92c2f6edd55e25ef6fb94434b7dc10cedf15))


### Documentation

* **python:** tidy the token_count redaction note ([5b0af54](https://github.com/Neoforge-Labs/hephaestus/commit/5b0af544e3b106fa364540a116120bcdc7069126))
