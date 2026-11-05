---
# GENERATED FILE - do not edit by hand. Source: docs/adr/0014-adopt-or-build.md.
# Regenerate with `uv run tools/gen_site_pages.py`; CI runs --check.
title: "0014. Adopt commodity components, build where we have an edge"
---

# 0014. Adopt commodity components, build where we have an edge

## Status

Accepted. Date: 2026-11-04.

## Context

Hephaestus keeps its full scope, but a solo operator cannot write every commodity component. Rule 8 requires checking the Adopt-or-build table before building one.

## Decision

We adopt, behind our own interfaces so each can be swapped: Keycloak (Apache 2.0) or a managed OIDC provider for login, passwords, MFA and SSO; the open-source Svix server for outbound webhooks; Restate or Temporal for long multi-step workflows; Dapr pub/sub for event brokers, conditional on a two-day spike holding up in Compose and on deploy targets, else native EventBus adapters; Inspect as the LLM eval runner; moonrepo with proto for polyglot builds; and Atlas for relational migrations across every language. We build in-house where we have an edge: money and ledger, idempotency, the spec and conformance suites, provenance and reproducibility, causal and statistics tooling, the UI registry, templates and the `heph` CLI.

## Consequences

Less code to own and review, and mature tools for the commodity parts. Each adopted tool is a dependency to track, and the Dapr choice is deferred to a spike in the adapters phase. Commodity components must not be hand-built without first checking this table.
