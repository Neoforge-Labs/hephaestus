---
# GENERATED FILE - do not edit by hand. Source: docs/adr/0011-hono-express-on-bun.md.
# Regenerate with `uv run tools/gen_site_pages.py`; CI runs --check.
title: "0011. Hono and Express on Bun for TypeScript backends"
---

# 0011. Hono and Express on Bun for TypeScript backends

## Status

Accepted. Date: 2026-11-04.

## Context

The design settles that TypeScript backends use Hono and Express, both running on Bun, with one service kit covering both. DataQRL's Express services stay DataQRL's and are not a source for it.

## Decision

TypeScript backends run on Bun, with Hono or Express. One service kit, `@hephkit/service`, covers both. It is written fresh; DataQRL's Express services stay DataQRL's.

## Consequences

One kit serves both frameworks and the `heph-bun` base image serves them. The kit must be tested against both. It is built on demand and enters as experimental, when the first TypeScript backend needs it.
