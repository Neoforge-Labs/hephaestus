---
# GENERATED FILE - do not edit by hand. Source: docs/adr/0009-grafana-cloud-otlp.md.
# Regenerate with `uv run tools/gen_site_pages.py`; CI runs --check.
title: "0009. Grafana Cloud over OTLP for production observability"
---

# 0009. Grafana Cloud over OTLP for production observability

## Status

Accepted. Date: 2026-11-04.

## Context

One trace must follow a request across every hop, LLM calls included, locally and in production, with no code change between the two.

## Decision

Production observability is Grafana Cloud, reached over OTLP. Locally everything lands in the `grafana/otel-lgtm` container on the standard OTLP ports. Production exporters point at Grafana Cloud through environment variables only. Shared attribute names live in `conventions/attributes.yaml` and generate constants for each language.

## Consequences

The same exporters and dashboards work in dev and production, and we avoid running a telemetry stack. We depend on a vendor's free and paid tiers, but because the wire protocol is OTLP the backend can be replaced by changing environment variables. The otel-lgtm fragment is for dev and test only.
