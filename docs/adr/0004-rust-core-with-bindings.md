# 0004. Rust core with language bindings

## Status

Accepted. Date: 2026-11-04.

## Context

Money, canonical JSON and content hashing, webhook signing and verification, UUIDv7 and idempotency fingerprints must behave identically in every language. Hand-porting them to Python and TypeScript lets the ports drift, and a drifting money primitive is a correctness bug. Ligase already runs a proven PyO3 + maturin setup.

## Decision

The correctness core is written once in Rust as `hephkit-core`. It is bound to Python with PyO3 (abi3 wheels, floor Python 3.12), to Bun and Node with napi-rs, and to the browser with WASM. The core does no I/O, holds no global state, never panics on input and returns `Result` everywhere. Go reimplements the core natively, because cgo would break static cross-compiles, and is held to the same conformance vectors. Each capability has one home language and one spec (CLAUDE.md rule 3). Toolchain note: Rust is pinned to a concrete stable release (1.99.1) in `rust-toolchain.toml`, with components `clippy` and `rustfmt`. That file carries the components, which `.prototools` cannot express, and rustup and cargo honour it natively for anyone not using proto. `.prototools` pins the same version so the two agree, alongside go, python, uv, node and bun. A concrete release is used rather than a floating `stable` because `cargo clippy -D warnings` is a CI gate, and a new Rust release could otherwise fail CI with new lints without any change to our code.

## Consequences

One implementation replaces drift-prone ports, and the Rust core is fuzzed with cargo-fuzz. Python wheels are built once per platform across Python versions. The cost is a Rust build step in the release pipeline, and a second, native Go implementation that must pass the shared vectors. The Rust version is declared in two files, `rust-toolchain.toml` and `.prototools`, which must be bumped together, and bumping the toolchain is a deliberate change that may bring new lints to fix.
