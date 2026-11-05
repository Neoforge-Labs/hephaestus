---
# GENERATED FILE - do not edit by hand. Source: docs/adr/0005-heph-spec-profiles-standards.md.
# Regenerate with `uv run tools/gen_site_pages.py`; CI runs --check.
title: "0005. heph-spec profiles existing standards"
---

# 0005. heph-spec profiles existing standards

## Status

Accepted. Date: 2026-11-04.

## Context

Behaviour shared by several languages needs a written specification, so that a Go service and a Python service agree because they target the same spec, not because someone kept them in sync by hand. Inventing protocols is costly and gets little review.

## Decision

`heph-spec` is a versioned document in `spec/`, released separately from the packages. It invents as little as possible and profiles existing standards: RFC 9457 problem details for errors, the IETF `Idempotency-Key` draft, Standard Webhooks, CloudEvents described with AsyncAPI, OpenAPI 3.1 and protobuf, OIDC and JWT, and OpenTelemetry semantic conventions including GenAI. Only four parts are original: the error-code registry, idempotency storage and replay semantics, how money is represented on the wire, and the research provenance record. Conformance vectors in `conformance/` pin the behaviour, and vectors come from independent sources, never from our own implementation (CLAUDE.md rule 2).

## Consequences

Interop leans on standards other people maintain. The four original parts get the most review, fuzzing and property tests. Each kit declares the spec version it implements, and `heph conform` and the vectors are tagged to that version. Changing behaviour means changing the spec and the vectors in the same PR.
