---
# GENERATED FILE - do not edit by hand. Source: docs/adr/0006-procrastinate-jobs.md.
# Regenerate with `uv run tools/gen_site_pages.py`; CI runs --check.
title: "0006. Procrastinate for jobs, with a Celery adapter"
---

# 0006. Procrastinate for jobs, with a Celery adapter

## Status

Accepted. Date: 2026-11-04.

## Context

Across the six product repos (Collie, Domus, Derma, Nocturna, NeoHealth and DataQRL) there are four different job systems (Celery, asynq, FastStream, APScheduler). Jobs that enqueue alongside a database write need to share the transaction, and trace context must follow the job.

## Decision

`hephkit.jobs` uses Procrastinate, a Postgres-backed queue, by default in every ingot, Collie included, whose rebuild moves off Celery. Enqueuing shares the DB transaction and propagates the trace. A Celery adapter sits behind the same interface, using the redis fragment, for workloads that need heavy fan-out or reuse existing Celery code.

## Consequences

No broker is needed for jobs, since Postgres is already present, and enqueue-in-transaction removes a class of lost-job bugs. The Celery adapter exists for workloads needing heavy fan-out. Collie has a migration to do, and the adapter must pass the same jobs contract suite before it is marked stable.
