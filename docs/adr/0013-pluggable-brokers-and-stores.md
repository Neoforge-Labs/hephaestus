# 0013. Pluggable brokers and stores with NATS, Postgres and pgvector defaults

## Status

Accepted. Date: 2026-11-04.

## Context

Projects differ in event, data and vector needs: DataQRL is on RabbitMQ, NeoHealth on MongoDB, research notebooks want embedded vectors. A single hard-wired backend would force rewrites, but a lowest-common-denominator API leaks.

## Decision

Events, data and vectors each sit behind a port: one interface in the platform spec, several adapters, and a contract suite every adapter must pass before it is marked stable. Defaults are NATS JetStream for events (Kafka and RabbitMQ also supported), Postgres for relational data and pgvector for vectors (Qdrant, LanceDB, Pinecone and Atlas also supported). Broker-specific features are reached through each adapter's `native()` escape hatch rather than faked. Correctness modules (money, ledger, audit, outbox, idempotency, auth) stay relational (CLAUDE.md rule 6).

## Consequences

Switching backends is a config change plus a contract-suite run. A port only counts as proven when at least two adapters pass its suite. Adapters are built in Python first, Go second, and TypeScript and Rust on demand. The cost is maintaining contract suites and several Compose fragments.
