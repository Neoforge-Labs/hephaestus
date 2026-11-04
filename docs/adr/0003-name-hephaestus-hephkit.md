# 0003. Name the kit Hephaestus, published as hephkit

## Status

Accepted. Date: 2026-11-04.

## Context

The kit needs one name across the repo, CLI and every package registry. Checked on 4 Nov 2026: `hephaestus` is taken on PyPI, npm and crates.io, and so is the `@hephaestus` npm scope; `heph` is taken as a package name on all three. `hephkit` is free on PyPI and crates.io, and so is the npm scope `@hephkit`.

## Decision

The brand, repo and CLI are Hephaestus, `Neoforge-Labs/hephaestus` and `heph`. Packages publish as `hephkit` on PyPI (imported as `hephkit`), `hephkit-core` on crates.io and `@hephkit/*` on npm. The Go module is `github.com/Neoforge-Labs/hephaestus/go` and images are `ghcr.io/neoforge-labs/heph-<runtime>`. Each project the kit creates is an "ingot".

## Consequences

One name across every registry beats a different one per ecosystem. The three registry names must be claimed before the first commit. Existing unrelated `heph` packages on PyPI and npm could clash only if installed alongside the CLI binary, which is an accepted, small risk.
