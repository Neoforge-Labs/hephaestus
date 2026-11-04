# Hephaestus — NeoForge's full-stack component and package suite

Nov 4, 2026 · @Kelyn Njeri

## The call

Name it **Hephaestus**, or `heph` at the command line. Build it as one public monorepo, `Neoforge-Labs/hephaestus`, spanning Rust, Go, Python, TypeScript and Terraform. A backend can be Python, Go, TypeScript or Rust, and a project can be one repo or a fleet of services. Hephaestus is built so that neither choice forces a rewrite.

Hephaestus is the smith of the gods, who forged the tools everyone else used. That is this library's role inside NeoForge: it is the forge itself, not anything the forge makes. Every project it creates is an **ingot**, a fresh cast of known composition, ready to be shaped into a product. `heph new collie` casts one, and `heph add data-table` and `heph dev up` work on it.

Why build it: every product and research project you start rebuilds the same dozen concerns, from experiment tracking and LLM plumbing down to Dockerfiles and CI. The ones that touch money are idempotency, webhooks, ledger, audit and money math. That is your stated edge, so each gets one hardened, property-tested home. Hephaestus grows only by extracting code you have already written twice. Collie's rebuild is the first product ingot and Domus the second; SAWA and NeoRx are the first research ingots.

## What your repos show

Backends run on all four of your languages. Python with FastAPI runs Collie, Derma, Nocturna, NeoHealth and SAWA. Go with chi runs Domus and DataQRL's Datafoundry, TypeScript with Express runs DataQRL's auth, CaseHub and notifications services, and Rust runs Ligase and DataQRL's Tauri desktop. Layouts swing too: Collie and Domus are one backend plus one frontend, while DataQRL is 8 backend services behind Traefik, talking over gRPC and RabbitMQ. Frontends are consistently Next.js 16 + React 19 + shadcn/Radix + TanStack Query + react-hook-form/zod.

| Product | Backend | Frontend | Built in-house each time |
| --- | --- | --- | --- |
| Collie (autobillr\_saas) | FastAPI, SQLAlchemy/asyncpg, Celery, Redis, Stripe + Paystack + Flutterwave, Resend, Twilio, WeasyPrint | Next 16, shadcn (20 ui files) | auth, authorize, idempotency, inbound + outbound webhooks, audit log |
| Domus | Go: chi, pgx, goose, asynq, zap | Next 16, shadcn (10 ui files) | `pkg/money`, `pkg/apierr`, ledger, audit, ratelimit, idempotency, Paystack |
| Derma | FastAPI, SQLAlchemy, Alembic, Anthropic | — | auth, security, ratelimit, audit |
| Nocturna | FastAPI, SQLAlchemy, psycopg, boto3 | — | settings, storage |
| NeoHealth | FastAPI + MongoDB | Expo 54 / React Native | auth |
| DataQRL (not yours to harvest) | FastAPI + Express services, Go Datafoundry | Vite React 18, shadcn (50 ui files) | auth service, tenancy, outbox, audit |

The repeats, counted across the six repos:

- Idempotency handling in 5 of 6; rate limiting, audit logging and webhook signature checks in 4 each.
- The shadcn component folder copied 3 times (20, 10 and 50 files), each drifting on its own.
- Auth written 4 separate ways (Collie middleware, Derma services, Domus `internal/auth`, DataQRL's Express service).
- 4 job systems (Celery, asynq, FastStream, APScheduler) and 3 PDF libraries (WeasyPrint, fpdf, ReportLab).

Your AI and research repos repeat just as much:

- Experiment plumbing: MLflow tracking, Prefect flows, DVC data versioning and marimo notebooks (SAWA).
- Causal inference with DoWhy and causal-learn (SAWA, NeoRx, plant-disease-causal).
- Reinforcement learning with Gymnasium and Stable-Baselines3 (NeoRx).
- Protein language models via ESM, transformers and accelerate (SAWA, NeoRx).
- Agents with LangGraph, MCP, mem0 and Ollama (Karani), and structured LLM output via instructor and the Anthropic SDK (Collie, Derma).

## Goals, non-goals, constraints

**Goals**

- A new product goes from `heph new` to a deployed app with auth, billing and tenants in one day.
- A new research project starts with experiment tracking, reproducible runs and a causal-analysis scaffold already wired in.
- Every result re-runs from its recorded config, data hash and seed, and says truthfully whether it reproduces exactly or only by provenance.
- The same app runs locally with one command and in production from one Terraform stack.
- One trace follows a request across every hop, LLM calls included: browser, API, model, job queue, webhook and back.
- Every primitive that touches money has exactly one implementation, backed by property tests.
- A bug fixed once reaches every product with a version bump.
- Each brand keeps its own look through tokens while sharing the same components.

**Non-goals**

- Domain science. Genomics types and bio file formats stay in Ligase. Hephaestus provides the domain-agnostic ML, causal and experiment infrastructure that Ligase builds on.
- A mobile kit for now. Only NeoHealth uses Expo.
- Replacing FastAPI or Next.js. Hephaestus is a set of libraries, not a framework.
- Kubernetes. Your products run on managed platforms (Render, Neon, Vercel), and a solo operator should keep it that way until a product outgrows them.

**Anti-goals (failures even if it works)**

- The kit owns your app's `main()` or hides behaviour behind magic.
- A kit upgrade breaks a product in production.
- A module gets built speculatively, with no product using it. The rule of two applies: nothing enters the kit until two products need it, unless it guards money.

**Constraints**

- **IP.** DataQRL's code belongs to DataQRL. You are a co-founder with 10% equity, not the owner. Backbone work belongs to Backbone as your client. Harvest only from NeoForge and personal repos: Collie, Domus, Derma, Nocturna, NeoHealth and Karani. Patterns you learned at DataQRL or Backbone (outbox, tenancy) get rewritten from scratch, not copied.
- **Build-to-sell.** A buyer must receive everything needed to run the product. A private dependency they can't own stalls due diligence. That is why the kit is public and MIT-licensed (see Architecture).

## Approaches

The pick is a hybrid: versioned packages for logic that must behave identically everywhere, a copy-in registry for UI that must look different per brand, and a template to wire them up.

| Approach | How it works | Gains | Costs |
| --- | --- | --- | --- |
| A. Packages for everything | pip and npm dependencies, semver | Fixes propagate everywhere | UI components fight you when each brand needs its own tweaks |
| B. Copy-in for everything (shadcn-style) | A CLI copies source into each app | You own every copy, with no lock-in | A money or idempotency bug fixed once stays broken in every copy. That is the drift you have today |
| C. Starter template only | Generate once, then diverge | Fastest start | Drifts from day two, so fixes never flow back |
| **Hybrid (pick)** | Packages for backend primitives, the API client and money formatting. A registry for UI. Copier template with `copier update` | Correctness is shared, looks stay per-brand, and existing apps can pull template fixes | Two release paths to maintain |

## Adopt or build

Hephaestus keeps its full scope. What changes is which parts it writes itself: it builds where you have an edge and wraps mature tools for the commodity parts, behind its own interfaces, so they can be swapped later.

| Concern | Adopt | What Hephaestus adds |
| --- | --- | --- |
| Login, passwords, MFA, SSO | An OIDC provider: Keycloak (Apache 2.0) self-hosted by default, or a managed provider per product | Token verification in every kit, API keys, RBAC and org membership |
| Outbound webhooks | The open-source Svix server, from the authors of the Standard Webhooks spec | The `webhooks.outbound` interface, tenant scoping, tracing |
| Long multi-step workflows (sagas, agent runs, media pipelines) | Restate or Temporal | A `workflows` port next to Procrastinate jobs; Nocturna's planned swap uses it |
| Event brokers across four languages | Dapr pub/sub, if a two-day spike holds up in Compose and on your deploy targets | The EventBus port, outbox and CloudEvents envelopes; native adapters only if the spike fails |
| LLM eval runner | Inspect | Case datasets, scorers, the CI regression gate |
| Polyglot monorepo builds | moonrepo, with its proto toolchain manager | Shared task presets and affected-only CI |
| Relational migrations | Atlas, one tool for every language | Migration templates and CI drift checks |
| Experiment tracking, agents, queues | MLflow, LangGraph, Procrastinate (already decided) | Wrappers for config, provenance, budgets and tracing |

Built in-house because this is where you have an edge: money and ledger, idempotency, the spec and conformance suites, provenance and reproducibility, the causal and statistics tooling, the UI registry, templates and the `heph` CLI.

## Architecture

Rust, Go, Python, TypeScript and Terraform all belong in Hephaestus under one rule: each capability has one home language and one written specification. A project in another language gets it through a binding to the Rust core, through a thin service kit that speaks the same protocol, or by calling it as a service. Nothing is reimplemented by hand, which is what keeps four backend languages maintainable by one person.

| Language | Job in Hephaestus | Why this language |
| --- | --- | --- |
| Rust | `hephkit-core`, the correctness core written once: money and allocation, canonical JSON and content hashing, webhook signing and verification, UUIDv7, idempotency fingerprints. Bound to Python with PyO3, to Bun and Node with napi-rs (Node-API) and to the browser with WASM. Also the axum service kit for Rust backends | One implementation replaces a Python port and a TS port that could drift. You already run this PyO3 + maturin setup in Ligase |
| Go | The `heph` CLI, Terraform tests (Terratest), small ops services (webhook relay, deploy agent), and the Go service kit for backends like Domus and Datafoundry-style compute services | Single static binaries, and the Terraform, Docker and Testcontainers tooling is Go-native. Go reimplements the core natively, because cgo would break static cross-compiles, and it must pass the same conformance vectors |
| Python | Product backend modules for FastAPI, plus the AI and research layers (catalogues below) | Home of the business modules, since they are harvested from Python products; also a service-kit language |
| TypeScript | UI registry, typed API client, Next.js instrumentation, and the service kit for Hono and Express backends on Bun | Your house frontend stack |
| HCL, Compose, Dockerfiles | Terraform modules and stacks, local-stack fragments, base images | Infrastructure every product repeats |

| Where | Name |
| --- | --- |
| Brand, repo, CLI | Hephaestus · `Neoforge-Labs/hephaestus` · `heph` |
| PyPI | `hephkit`, imported as `hephkit` |
| npm | `@hephkit/*` |
| crates.io | `hephkit-core` |
| Go | `github.com/Neoforge-Labs/hephaestus/go` |
| Terraform | `github.com/Neoforge-Labs/hephaestus//terraform/modules/<name>` |
| Container images | `ghcr.io/neoforge-labs/heph-<runtime>` |

**Names (checked 4 Nov 2026).** `hephaestus` is taken on PyPI, npm and crates.io, and so is the `@hephaestus` npm scope. `heph` is taken as a package name on all three. `hephkit` is free on PyPI and crates.io, and so is the npm scope `@hephkit`. One name across every registry beats a different one per ecosystem, so claim all three before the first commit.

The CLI binary is `heph`. Existing packages named `heph` on PyPI and npm are unrelated; they could only clash if one were installed alongside it.

```
hephaestus/
  core/              # Rust: hephkit-core + PyO3 and WASM bindings
  python/hephkit/      # Python package, modules behind extras
  packages/          # @hephkit/config, client, core (WASM)
  registry/          # shadcn-format UI components + brand presets
  go/                # CLI, service kit, ops services, Terratest suites
  conformance/       # shared JSON vectors every language must pass
  conventions/       # telemetry attribute names → generated constants per language
  docker/            # base images + Dockerfile templates
  compose/           # local-stack fragments
  terraform/         # modules/ and stacks/
  .github/workflows/ # reusable CI workflows
  templates/         # Copier templates: saas, research
  docs/              # Nextra site at heph.neoforgelabs.tech (also serves /r/*.json)
```

**How products consume it**

- Python: `uv add "hephkit[money,idempotency,webhooks,auth]"`. One version number, with the Rust core shipped inside prebuilt wheels.
- UI: `heph add data-table`, which wraps `npx shadcn add https://heph.neoforgelabs.tech/r/data-table.json`.
- TypeScript: the `@hephkit/*` npm packages.
- Go: `go get github.com/Neoforge-Labs/hephaestus/go`. The CLI comes from release binaries or `go install`.
- Infrastructure: Terraform modules pinned by git tag, and CI through `uses: Neoforge-Labs/hephaestus/.github/workflows/python-ci.yml@v1`.

**Why public MIT.** A buyer inherits an MIT dependency with no licence negotiation, so a sale stays clean. It also fits building in public. Plumbing is not your moat; products, customers and data are. Product-specific logic never enters Hephaestus.

## heph-spec

The spec is the product, and the libraries are its implementations. `heph-spec` is a versioned document in `spec/`, released separately from the packages. Each version of `heph conform` and the conformance vectors is tagged to the spec version it checks. A kit declares which spec version it implements, so a Go service and a Python service agree because they target the same spec, not because someone kept them in sync by hand.

It invents as little as possible. Most of it is a profile of existing standards:

| Concern | Standard it profiles |
| --- | --- |
| Errors | RFC 9457 problem details |
| Idempotent requests | The IETF `Idempotency-Key` header draft |
| Webhooks | Standard Webhooks |
| Events | CloudEvents, described with AsyncAPI |
| HTTP and RPC contracts | OpenAPI 3.1, protobuf |
| Identity | OIDC and JWT |
| Telemetry | OpenTelemetry semantic conventions, including GenAI |

Only four parts are original: the error-code registry, idempotency storage and replay semantics, how money is represented on the wire, and the research provenance record. Those four get the most review, fuzzing and property tests.

## Polyglot services and layouts

Contracts are written once and every language generates its code from them. A thin service kit per language implements the shared platform protocol, and one black-box conformance suite proves every kit behaves the same. Moving a project from one deployable to a fleet of services then becomes a deployment change, not a rewrite.

**Contracts, written once** (in each ingot's `contracts/` folder)

| Contract | Format | Code generated for |
| --- | --- | --- |
| HTTP APIs | OpenAPI 3.1 | TypeScript (openapi-typescript), Go (oapi-codegen), Python (pydantic models via datamodel-code-generator), Rust (progenitor) |
| Service-to-service RPC | Protobuf, managed with Buf | gRPC stubs for Go, TypeScript, Python and Rust (tonic), the style DataQRL already uses |
| Events | AsyncAPI with JSON Schema payloads in CloudEvents envelopes | Typed publishers and consumers in all four languages |
| Platform protocol | Hephaestus spec: error codes, `Idempotency-Key` semantics, token claims, webhook signatures, telemetry attributes | Every service kit |

**Service kits: the same behaviour, idiomatic per framework**

| Language | Framework | Kit | Harvest from |
| --- | --- | --- | --- |
| Python | FastAPI | `hephkit` | Collie, Derma |
| Go | chi on `net/http` | `hephaestus/go` | Domus `pkg/` (money, apierr, crypto, token) |
| TypeScript | Hono or Express, on Bun | `@hephkit/service` | Written fresh; DataQRL's Express services stay DataQRL's |
| Rust | axum with tower middleware | `hephkit-axum` | Written fresh |

Every kit provides:

- problem+json errors with the shared codes
- `Idempotency-Key` middleware
- JWT and API-key verification (issuing tokens stays in the auth module)
- OpenTelemetry with the shared attributes
- `/healthz` and `/readyz` endpoints
- env config that fails fast
- graceful shutdown
- structured logs that carry trace ids
- a transactional outbox with event publishing

Money, hashing and signatures come from the Rust core in every language: via PyO3, napi-rs and native Rust, plus a native Go port held to the conformance vectors.

**One conformance suite.** `heph conform http://localhost:8000` is a black-box test suite in the Go CLI. It works against any service in any language, checking error shapes, idempotent replays, auth rejection, health endpoints, trace propagation and event envelopes. Every kit passes it in CI, and so does every service an ingot ships.

**Monolith to services without a rewrite**

- **Default layout:** a modular monolith. It is one deployable whose modules talk only through their contracts. Import boundaries are enforced with import-linter in Python and `internal/` packages in Go.
- **One event path:** events travel through an in-process bus in the monolith and through a broker in a service layout, with the same schemas and the same outbox. Splitting a module out means giving it its own deployable, swapping the transport and deploying.
- **Broker:** NATS JetStream, Kafka or RabbitMQ behind one event interface, chosen per project with NATS as the default (see Pluggable infrastructure).
- **Edge:** Traefik in front of a service layout, as in DataQRL. A monolith uses plain platform routing.
- **Repo shape:** a monorepo for both layouts by default, with uv, pnpm, Cargo and Go workspaces side by side. moonrepo runs tasks across all four languages and builds only what a change affects, with tool versions pinned by its proto toolchain manager. A service can still move to its own repo later, because the boundary is its contract, not the repo.

`heph new` takes `--layout monolith|services` and `--api python|go|ts|rust`. `heph add service billing --lang go` adds a service to an existing ingot.

## Pluggable infrastructure

Events, data and vectors each sit behind a port: one interface in the platform spec, several adapters, and a contract test suite that every adapter must pass before it is marked `stable`. A project picks its backends at `heph new` and can switch later by changing config and running the suite, without touching business code.

```
heph new my-app --events nats|kafka|rabbitmq|memory --db postgres|mysql|sqlite|mongo --vector pgvector|qdrant|lancedb|pinecone|atlas
```

**Events: the `EventBus` port**

| Adapter | Best for | Local dev fragment |
| --- | --- | --- |
| In-process | Modular monoliths and tests | none |
| NATS JetStream (default) | Most service layouts: one small binary with streams, request-reply and a key-value store | `nats` |
| Kafka | High-volume streams, long retention, replaying history from an offset, analytics pipelines | `kafka`, running Redpanda (Kafka-API compatible, a single container) |
| RabbitMQ | Work queues and routing topologies, and projects already on it such as DataQRL | `rabbitmq` |

The shared interface covers what all three do well: publish and subscribe with CloudEvents envelopes, at-least-once delivery, consumers that dedupe on event id, ordering per partition key, retries with backoff, and dead-letter handling. It also carries trace context and is fed by the transactional outbox. Features that only one broker has, such as Kafka log compaction and offset replay or RabbitMQ exchange routing, are reached through each adapter's `native()` escape hatch instead of being faked across all three. A leaky lowest-common-denominator broker API is the usual way these abstractions fail.

**Data: SQL and NoSQL ports**

| Kind | Adapters | Where it fits |
| --- | --- | --- |
| Relational | Postgres (default), MySQL, SQLite (tests and embedded) | System of record. Money, ledger, audit, outbox, idempotency and auth require it |
| Document | MongoDB | Flexible product data, as NeoHealth uses today |
| Key-value | Redis or Valkey | Cache, rate limits, sessions, the Celery adapter |
| Graph | Neo4j | Relationship-heavy data and knowledge graphs; DataQRL is the pattern, rebuilt rather than copied |
| Analytical | DuckDB (embedded), ClickHouse (server) | Research data, reporting, event analytics |
| Objects | S3 API: SeaweedFS locally, R2 or S3 in production | Files, datasets, checkpoints |

The correctness modules stay relational on purpose. The ledger's postings-must-balance rule, append-only audit, and outbox-in-the-same-transaction depend on SQL constraints and ACID transactions, and the contract suite would reject a document-store adapter for them. Everything else can live wherever the product's data fits best. Per language, relational access uses SQLAlchemy (Python), sqlc on pgx (Go), Drizzle (TypeScript) and sqlx (Rust). Each ingot's relational schema is owned by Atlas, whichever languages its services use.

**Vectors for RAG: the `VectorStore` port**

| Adapter | Best for |
| --- | --- |
| pgvector (default) | Most products: vectors sit beside the rows they describe, in the same transaction and backups |
| Qdrant | Large collections, heavy filtered search, or a dedicated retrieval service |
| LanceDB | Embedded and file-based; research notebooks and local experiments with no server |
| Pinecone | Fully managed and serverless, when you would rather not run anything |
| MongoDB Atlas Vector Search | Products whose data already lives in MongoDB |

The port covers upsert, delete, similarity search with metadata filters, hybrid scoring with keyword search, and namespaces per tenant. Embeddings are cached by content hash, so switching vector store re-indexes without re-embedding. `ai.retrieval` and `lab.embed` both sit on this port, so a retrieval pipeline built in a notebook on LanceDB ships to a product on pgvector unchanged.

**Language coverage.** Ports and contract suites exist for all four languages from the start. Adapters are built in Python first, Go second, and in TypeScript and Rust when a project in that language needs them. Each new adapter is a matter of passing an existing suite, not designing a new interface.

## Business modules (Python home)

Tier 1 is the correctness core and gets built first. Tier 2 is SaaS plumbing that every micro-SaaS needs. Tier 3 is on demand. "Rust core" means the logic lives in `hephkit-core`, and the Python module is a thin, typed wrapper around it.

| Module | What it gives you | Implemented in | Harvest from | Tier |
| --- | --- | --- | --- | --- |
| `hephkit.money` | Money as integer minor units with ISO 4217 exponents (KES 2, JPY 0, BHD 3). Splitting never loses or creates a cent, and rounding modes are explicit | Rust core | Domus `pkg/money` | 1 |
| `hephkit.hashing` | Canonical JSON, content hashes, UUIDv7, idempotency fingerprints | Rust core | Nocturna's content-addressing rules | 1 |
| `hephkit.errors` | RFC 9457 problem+json exceptions and FastAPI handlers, with stable error codes | Python | Domus `pkg/apierr` | 1 |
| `hephkit.idempotency` | `Idempotency-Key` middleware: stores request hash and response, replays a repeated key, rejects the same key with a different body. `@idempotent` for workers, keyed on event id | Python on Rust fingerprints | Collie, Domus | 1 |
| `hephkit.webhooks.inbound` | Verifiers for Stripe, Paystack, Flutterwave, Plaid, Resend and Twilio. M-Pesa callbacks use an IP allowlist plus a transaction query-back. Stores the raw event, dedupes by provider event id, processes async | Rust core (signatures) + Python | Collie `routes/webhooks` | 1 |
| `hephkit.webhooks.outbound` | Subscriptions and delivery through a self-hosted Svix server (Standard Webhooks signing, retries, delivery log), behind a heph interface with tenant scoping and tracing | Rust core (signing) + Python | Collie `webhook_subscription` / `webhook_delivery` | 1 |
| `hephkit.ledger` | Double-entry journal where postings must sum to zero per currency (a DB constraint). Mistakes are fixed with reversals, never edits. Balance snapshots | Python on Rust money | Domus `internal/ledger` | 1 |
| `hephkit.audit` | Append-only log of actor, tenant, action and before/after diff. Optional hash chain for tamper evidence | Python on Rust hashing | Collie, Derma, Domus | 1 |
| `hephkit.outbox` | Transactional outbox, so a DB write and its event never diverge. Carries the trace context forward | Python | Written fresh | 1 |
| `hephkit.testing` | Postgres via testcontainers, factories, a frozen clock, provider fakes, contract tests | Python | All | 1 |
| `hephkit.settings` | pydantic-settings base with env profiles; fails fast on a missing secret | Python | All Python repos | 2 |
| `hephkit.db` | Async engine and session, a base model with UUIDv7 ids and timestamps, cursor pagination, an Alembic env template | Python | Collie, Derma | 2 |
| `hephkit.auth` | Token verification against an OIDC provider (Keycloak by default), API keys (prefix plus hashed secret), RBAC and org membership. Login, passwords and MFA live in the provider | Python | Collie, Derma, Domus | 2 |
| `hephkit.tenancy` | Tenant context var, scoped-query guard, Postgres row-level security helpers | Python | Domus | 2 |
| `hephkit.observability` | One call sets up OpenTelemetry traces, metrics and logs, structlog with trace ids, and PII redaction, using the shared attribute names | Python | Collie | 2 |
| `hephkit.ratelimit` | Redis token bucket as a FastAPI dependency | Python | Derma, Domus | 2 |
| `hephkit.jobs` | Procrastinate (Postgres-backed queue) by default in every ingot, Collie included. Enqueuing shares the DB transaction and propagates the trace. A Celery adapter sits behind the same interface for workloads that need it | Python | Written fresh | 2 |
| `hephkit.notify` | Email (Resend) and SMS (Twilio, Africa's Talking) behind one interface, Jinja templates, a test fake | Python | Collie | 2 |
| `hephkit.billing` | Stripe subscriptions, entitlements (plan → features and limits), usage metering, a Paystack adapter | Python | Collie | 2 |
| `hephkit.storage` | S3-compatible client with presigned upload and download. SeaweedFS locally, R2 or S3 in production | Python | Nocturna, Collie | 2 |
| `hephkit.documents` | Jinja → PDF via WeasyPrint for invoices, receipts and statements | Python | Collie | 3 |
| `hephkit.llm` | Structured output via instructor, retries, per-tenant token and cost metering, prompt versions, a small eval harness, PII redaction before sending | Python | Derma | 3 |

**Also shipped as services.** Auth, billing, notify, inbound and outbound webhooks, ledger and audit are also published as container images that speak the shared contracts. A Go, TypeScript or Rust service, or any project in a service layout, calls them instead of reimplementing them. The library and the service are the same code, so their behaviour cannot drift apart.

**Jobs call.** Procrastinate from the start, Collie included: its rebuild moves its jobs off Celery. Celery stays available through the adapter, using the redis fragment, when a workload needs heavy fan-out or reuses existing Celery code.

## AI and research layers

Two Python layers sit on the same core: `hephkit.ai` for AI inside products, and `hephkit.lab` for research. Both use the Rust content hashing, so a prompt, a dataset, a checkpoint and a result are all addressed the same way, and lineage runs unbroken from raw data to a shipped feature or a published figure. Tiers mean the same as in the backend catalogue.

**Product AI: `hephkit.ai`**

| Module | What it gives you | Harvest from | Tier |
| --- | --- | --- | --- |
| `ai.llm` | One gateway over Anthropic, OpenAI and local models (Ollama or vLLM through their OpenAI-compatible APIs). Structured output into pydantic models, retries, fallbacks, streaming. Every call records tokens and cost against the tenant and is checked against a per-run budget before it fires | Collie, Derma, Karani | 2 |
| `ai.prompts` | Versioned, content-hashed prompts, so any response traces back to the exact prompt that produced it | Written fresh | 2 |
| `ai.evals` | Inspect as the runner, with heph case datasets, scorers (exact match, schema diff, model-graded rubric) and a CI gate that fails on regression. Production traces can be sampled into new cases | Written fresh | 2 |
| `ai.guard` | PII redaction before anything leaves (Presidio), output schema validation, and tool or retrieved text treated as untrusted input | Derma | 2 |
| `ai.agents` | LangGraph as the runtime. Hephaestus supplies the Postgres checkpointer, tool registry, budget ceilings, human-approval interrupts and tracing | Karani | 3 |
| `ai.mcp` | Expose a FastAPI service's tools as an MCP server in a few lines, plus an MCP client | Karani | 3 |
| `ai.retrieval` | Chunking, hybrid search (keyword plus vectors), reranking and an embedding cache keyed by content hash, on the VectorStore port: pgvector by default, or Qdrant, LanceDB, Pinecone or MongoDB Atlas Vector Search | Karani | 3 |
| `ai.memory` | Agent memory over Postgres, with a mem0 adapter | Karani | 3 |
| `ai.serve` | Serving templates: vLLM for LLMs, FastAPI with request batching for small PyTorch or ONNX models | NeoRx | 3 |
| `ai.voice` | Speech-to-text, text-to-speech and telephony adapters | Sonra, ADAM | 3 |

LLM calls emit OpenTelemetry's GenAI semantic conventions (`gen_ai.*` attributes for model, tokens and cost), so they show up in the same traces and dashboards as everything else. The registry adds `ChatPanel` (streaming), `ToolCallView`, `CitationList` and `FeedbackButtons`, wired to `ai.evals`. DataQRL's LangGraph orchestration stays DataQRL's: `ai.agents` is rebuilt from Karani, not copied.

**Research: `hephkit.lab`**

| Module | What it gives you | Harvest from | Tier |
| --- | --- | --- | --- |
| `lab.config` | Typed experiment configs (pydantic) with command-line overrides. Each run's resolved config is hashed and stored | SAWA, NeoRx | 1 |
| `lab.repro` | Seeds Python, NumPy and PyTorch, sets deterministic flags, captures git SHA, lockfile hash and GPU driver. Each artifact is labelled `deterministic` or `provenance-only`, the same tiering Nocturna uses | Nocturna, SAWA | 1 |
| `lab.track` | MLflow wrapper: config, metrics, artifacts and dataset hashes on every run, linked to its trace | SAWA `tracking.py` | 1 |
| `lab.data` | Content-addressed dataset snapshots on object storage via DVC, Polars and DuckDB loaders, and data cards | SAWA | 1 |
| `lab.causal` | DAG specification, identification and estimation through DoWhy, a refutation suite that runs by default, causal-learn discovery adapters, and a report generator | SAWA `causal/`, NeoRx | 1 |
| `lab.stats` | Multi-seed aggregation, bootstrap confidence intervals, effect sizes and the right tests, so a claimed improvement survives review | Written fresh | 1 |
| `lab.flows` | Prefect flow templates that run locally or on GPU workers | SAWA | 2 |
| `lab.train` | Thin PyTorch helpers on accelerate: mixed precision, checkpointing to object storage as safetensors, early stopping | SAWA `foundation_models/`, NeoRx | 2 |
| `lab.rl` | Gymnasium environment scaffolding, Stable-Baselines3 baselines, and an evaluation harness across seeds and episodes | NeoRx | 2 |
| `lab.embed` | Generic Hugging Face model loading and cached embedding extraction. ESM-specific wrappers stay in Ligase | SAWA, NeoRx | 2 |
| `lab.paper` | Consistent figure styling, a methods and provenance paragraph generated from `lab.repro` records, `CITATION.cff`, and Zenodo DOI on each release | SAWA | 2 |
| `lab.cogsci` | jsPsych experiment templates served from the Next.js stack, participant, session and consent records, a trial-level data schema, psychometric and reaction-time analysis, and drift-diffusion fitting via PyDDM | Your first cog-sci project | 3 |

No cognitive-science repo turned up in your GitHub, so `lab.cogsci` gets harvested from your first one rather than designed up front. Ligase depends on `hephkit-core` and `hephkit.lab`, never the reverse.

**Infrastructure additions**

- Compose: the `postgres` fragment uses a pgvector-enabled image, and three new fragments arrive: `ollama` (local models), `mlflow` (tracking server on Postgres with artifacts in SeaweedFS) and `prefect` (flow server).
- Image: `heph-ml`, with CUDA, uv and PyTorch, for training and serving.
- GPU workers: Prefect work pools on your home-lab machine or a rented cloud GPU, chosen per run.
- CI: an `ml-ci` reusable workflow that runs the eval regression gate, a CPU smoke-train on a data sample, and every notebook end to end.

## Frontend packages

The registry replaces your three drifting shadcn folders with one themed source. The composite screens you keep rebuilding become one-command installs.

| Piece | What it gives you | Delivered as |
| --- | --- | --- |
| `@hephkit/config` | tsconfig, Biome lint/format, a Tailwind v4 preset built on CSS-variable design tokens | npm package |
| Brand presets | Token sets for Collie, Domus (#4ade80 on #0a0a0a), NeoHealth (#0E6944) and NeoForge | Registry |
| Base components | The shadcn set, maintained once and themed only through tokens | Registry |
| `AppShell` | Sidebar, top bar, org switcher, `cmdk` command palette | Registry |
| `DataTable` | TanStack Table with server pagination, sort and filter, column visibility, CSV export | Registry |
| `Amount` / `MoneyInput` | Currency-aware display and entry on minor units, using the same Rust money logic via WASM | Registry + `@hephkit/core` |
| Form kit | react-hook-form + zod fields; server problem+json errors map onto the matching fields | Registry |
| Auth screens | Sign in, sign up, reset, MFA, invite accept | Registry |
| Settings screens | Profile, team and roles, API keys, billing and plan, webhooks | Registry |
| Small parts | `PageHeader`, `StatCard`, `EmptyState`, `ConfirmDialog`, presigned `FileUpload`, `DateRangePicker`, `AuditTimeline`, onboarding stepper | Registry |
| `@hephkit/client` | Types generated from FastAPI's OpenAPI schema (openapi-typescript + openapi-fetch) with TanStack Query hooks. Adds an `Idempotency-Key` to every POST and PATCH, turns problem+json into typed errors, refreshes tokens, sends `traceparent` | npm package |
| `@hephkit/core` | WASM build of `hephkit-core`: money, hashing, signature checks in the browser and in Node | npm package |
| `@hephkit/otel` | Next.js `instrumentation.ts` setup and browser tracing, so a click and its API call share one trace | npm package |

The docs site runs on Nextra, as Karani's docs already do, and also serves the registry JSON. A mobile kit (`@hephkit/native`) waits until a second Expo app exists.

## DevOps layer

The same app runs locally from Compose fragments and in production from a Terraform stack, with OpenTelemetry tying both together. `heph dev up` and `heph deploy plan` are the only two commands a product needs.

**Docker**

- Base images on GHCR: `heph-python` (uv, slim, non-root), `heph-node` (Next.js standalone output), heph-bun (TypeScript services), `heph-go` (distroless static) and a Rust builder image for wheels and WASM.
- Multi-stage Dockerfile templates with healthchecks and a pinned digest for every base image.
- Every image gets a Syft SBOM, a Trivy scan and keyless cosign signing in CI.

**Compose local stack.** Each service is its own fragment in `compose/`, and an app's compose file pulls in only what it needs with `include:`.

| Fragment | Image | For |
| --- | --- | --- |
| `postgres` | postgres | Database, plus the Procrastinate job queue |
| `objects` | SeaweedFS | S3-compatible storage. Not MinIO: MinIO withdrew its public images on 30 Sep 2026, which is why Nocturna already moved off it |
| `redis` | redis | Only when rate limiting, caching or the Celery adapter is on |
| `telemetry` | grafana/otel-lgtm | Collector, Prometheus, Tempo, Loki, Pyroscope and Grafana in one container, on the standard OTLP ports 4317/4318. Dev and test only |
| `mail` | Mailpit | Catches outgoing email |
| `stripe` | stripe-cli | Forwards real Stripe test webhooks to the local API |
| `nats` | nats (JetStream on) | Event broker for service layouts |
| `edge` | Traefik | Routing and TLS in front of a service layout |
| `kafka` | Redpanda | Kafka-API broker for projects on the Kafka adapter |
| `rabbitmq` | rabbitmq (management) | Projects on the RabbitMQ adapter |
| `mongo` | mongo (single-node replica set) | Document data; a replica set so transactions work locally |
| `neo4j` | neo4j (community) | Graph data |
| `qdrant` | qdrant | Dedicated vector store |

**Tracing and observability**

- `conventions/attributes.yaml` defines the shared attribute names once: `tenant.id`, `user.id`, `idempotency.key`, `job.name`, `webhook.provider`, `money.currency`. It generates constants for Python, TypeScript, Go and Rust, so a dashboard query works across every service.
- Setup is one call per runtime: `hephkit.observability` (Python), `@hephkit/otel` (Next.js and browser), `hephaestus/go/otel` (Go), `tracing` + `tracing-opentelemetry` (Rust).
- The trace context rides through the outbox, the job queue and outbound webhooks, so a payment can be followed from the click to the webhook that confirms it.
- Logs carry `trace_id`. Locally everything lands in otel-lgtm. In production the same OTLP exporters point at Grafana Cloud through environment variables, with no code change.

**Terraform modules** (OpenTofu-compatible, each pinned by version)

| Module | Provider | Note |
| --- | --- | --- |
| `render-service` | `render-oss/render` (official) | API, worker and cron services; secrets as env groups |
| `neon-postgres` | `kislerdm/neon` | Community-maintained, though Neon sponsors it. Pin the version: schema changes on upgrade can force resource replacement |
| `cloudflare-zone` | `cloudflare/cloudflare` | DNS, TLS, R2 buckets for object storage |
| `vercel-project` | `vercel/vercel` | Next.js frontends where Vercel is used |
| `grafana-cloud` | `grafana/grafana` | Stack, OTLP access token, alert rules |
| `github-repo` | `integrations/github` | Branch protection, Actions secrets, environments |

`terraform/stacks/saas-app` composes those modules into one product. State is remote and locked.

Each module ships with `terraform test` for plan-level checks, a Terratest suite that applies against a sandbox account and tears down, and tflint plus Checkov in CI. Since your production Terraform experience is limited, a module only counts as stable once it has applied and destroyed cleanly in the sandbox.

**Reusable CI.** These are `workflow_call` workflows in `.github/workflows/`, so each product's CI is about ten lines: `python-ci`, `node-ci`, `go-ci`, `rust-wheels` (maturin builds for Linux x86\_64/arm64 and macOS arm64), `docker-publish` (build, SBOM, scan, sign), `terraform-plan` (plan posted as a PR comment) and `release`.

Sources: [Render Terraform provider](https://render.com/docs/terraform-provider) · [Neon Terraform provider](https://neon.com/docs/reference/terraform) · [grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm)

## App template

`heph new my-app` casts a new ingot from the Copier template at `templates/saas` and produces a deployable product, infrastructure included. Later, `heph update` runs `copier update`, which pulls template improvements into apps that already exist. That is why Copier wins over cookiecutter here.

It asks four questions: product name, brand preset, billing provider (Stripe or Paystack), and whether the app is multi-tenant. It then generates:

- `api/`: the API in the language chosen with --api (FastAPI by default), its service kit wired up, and the business modules either imported (Python) or called as services (Go, TypeScript, Rust). With --layout services this becomes services/\<name>/ per service, plus the nats and edge fragments
- `worker/`: Procrastinate jobs
- `web/`: Next.js with AppShell, auth, settings and billing screens, the generated client and `@hephkit/otel`
- `compose.yaml` including the postgres, objects, telemetry, mail and stripe fragments
- Dockerfiles built on the Hephaestus base images
- `infra/`: a Terraform root module using `stacks/saas-app`
- `.github/workflows/`: about ten lines calling the reusable workflows, plus a check that fails when the OpenAPI client is stale
- `.env.example` and a `Makefile`

Cut the template only after Collie and one other product run on Hephaestus. A template built before that encodes guesses.

**Research template.** `heph new --template research sawa-2` casts a research ingot instead. It includes typed configs and a `lab.repro` entry point, MLflow and DVC wired to object storage, Prefect flows, a `causal/` scaffold with DAG, estimate and refute stages, marimo notebooks, a `paper/` folder with figure styles and the generated methods section, `CITATION.cff`, and a release workflow that mints a Zenodo DOI. Cut it once SAWA and NeoRx both run on `hephkit.lab`.

## Quality bar

Here, "elite" means each guarantee is checked by a machine on every commit, not trusted to review.

- **Invariants tested, not examples.** Property tests (proptest in Rust, Hypothesis in Python, fast-check in TypeScript) prove an allocation never loses or creates a cent and every journal entry balances.
- **One truth across languages.** `conformance/*.json` vectors cover rounding, allocation, currency exponents, hashing, webhook signatures and error codes. The Rust core, its Python and WASM bindings, and the Go kit all run the same file in CI.
- **Results that reproduce.** A `deterministic` experiment re-run from its config, data hash and seed must match bit for bit in CI. Reported metrics come from at least three seeds with confidence intervals, never one lucky run.
- **AI behaviour is gated.** Every prompt or model change runs the eval suite, and a regression fails the build like a failing unit test.
- **Strict everywhere.** `mypy --strict`, TypeScript `strict`, `cargo clippy -D warnings`, and `go vet` + staticcheck. A public function without types fails CI.
- **Coverage gates.** At least 90% on Tier 1 and the Rust core, and 80% on Tier 2, enforced in CI.
- **Every provider has a fake.** Each external service, LLM providers included, ships an interface, a real adapter and a fake. One contract test suite runs against both, so product tests can use the fake safely and offline.
- **Infrastructure is tested like code.** `terraform test` and Terratest for modules, tflint and Checkov for policy, Trivy for images. Every image is signed and every Compose fragment is boot-tested in CI.
- **Safe upgrades.** Semver, a changelog, and one minor version of deprecation warning before anything is removed. Renovate opens upgrade PRs in each product. Every module carries a maturity level: `experimental`, `beta` or `stable` (see below).
- **Security in CI.** Tests prove secrets and PII never reach logs or model providers. pip-audit, npm audit, cargo-audit, govulncheck and CodeQL run on every PR.
- **Docs that run.** Every module page carries an example that CI executes, and every notebook runs end to end.

**Maturity levels.** Full scope is safe only if breadth can't leak unproven code into production. Every module, kit and adapter carries one of three labels, shown on its docs page and checked by `heph doctor`:

| Level | Means | Promotion requires |
| --- | --- | --- |
| `experimental` | API may change; not for production | — |
| `beta` | API settled; usable in production off the money path | Passes its contract suite, has docs with a runnable example, used by one ingot |
| `stable` | Covered by semver and the deprecation policy | Coverage gate met, used by two ingots in production, passes ecosystem CI |

Money, ledger, idempotency and webhook modules can only be used in a production money path once they are `stable`, and `heph doctor` fails a deploy that breaks this rule.

**Developer experience and release**

- **The five-minute path comes first.** The tutorial is written before the code: `heph new`, then `heph dev up`, then a running app with a trace in Grafana, in under five minutes on a clean machine. CI measures `heph dev up` start time and install size, and fails if they grow past their budgets.
- **Thin templates.** Templates only wire packages together, and behaviour lives in versioned packages. That keeps `heph update` from turning into merge conflicts, and every package still works without the CLI.
- **Ecosystem CI.** Collie, Domus, SAWA and NeoRx, at pinned commits, run against the kit's main branch on every PR, so a breaking change shows up before a release, not after.
- **A boring Rust core.** No I/O inside it. abi3 wheels give one build per platform across Python versions, with musl and ARM covered, and napi-rs prebuilds cover Bun and Node. Money and signature parsing are fuzzed continuously with cargo-fuzz.
- **Supply chain.** Releases use trusted publishing from GitHub Actions on each registry that supports it, plus Sigstore attestations. Core and kits move in lockstep on one version number, managed by release-please. A short threat model covers the money, idempotency and webhook modules.
- **Errors that teach.** Every error code resolves to a docs page; for example, `HEPH-IDEMP-409` links to its own explanation and fix.
- **Decision records.** Each decision in this doc becomes a numbered ADR in `docs/adr/`, starting with the ones settled on 4 Nov 2026.

## Rollout

Hephaestus is built along two tracks that share the core: a product track riding the Collie rebuild, and a research track harvested from SAWA and NeoRx. Each phase ends at a gate a real project has to pass. Week counts are estimates. Starting with Rust puts the core on Collie's critical path, but Ligase has already proven the maturin wheel pipeline, so the risk is packaging rather than design.

1. **Weeks 1–2: Core and local stack.** Write heph-spec v0.1 and the five-minute tutorial first. Then set up the repo with moonrepo across cargo, uv, pnpm and Go workspaces, the docs site, the reusable CI with trusted publishing, and the first ADRs. Build `hephkit-core` (money, hashing, signatures) with Python wheels and conformance vectors. Then errors, settings and observability, the base images, and the Compose fragments with otel-lgtm. *Gate: Collie imports `hephkit.money` and runs on `heph dev up` with traces visible in Grafana.*
2. **Weeks 3–4: Collie core (product).** Build idempotency, inbound webhooks (Stripe, Paystack), audit, db, auth, notify, testing and Procrastinate jobs (moving Collie off Celery), harvested from `autobillr_saas` as the rebuild touches each area. Write the platform protocol spec and the heph conform suite alongside, with the Python kit the first to pass it. *Gate: Collie runs on Hephaestus in staging.*
3. **Weeks 5–6: Research core.** Build `lab.config`, `lab.repro`, `lab.track`, `lab.data`, `lab.causal` and `lab.stats`, plus the `mlflow` fragment, harvested from SAWA and NeoRx. *Gate: a SAWA causal analysis and a NeoRx RL run each re-execute from their recorded config and data hash, match exactly, and show up in MLflow with their provenance class.*
4. **Weeks 7–8: Money movement, UI and product AI.** Build ledger, outbox plus Procrastinate, outbound webhooks and billing with entitlements. Ship the registry, the WASM `@hephkit/core`, the generated client and `@hephkit/otel`. Add `ai.llm`, `ai.prompts`, `ai.evals` and `ai.guard`. *Gate: one trace runs from a click in Collie's UI, through an LLM call with its tokens and cost, to the Stripe webhook that settles it.*
5. **Weeks 9–10: Infrastructure, the CLI and ML infra.** Build the Terraform modules and `stacks/saas-app` with Terratest against a sandbox, the Go `heph` CLI (`new`, `add`, `dev up`, `deploy plan`, `doctor`), the `heph-ml` image, Prefect GPU work pools, and `lab.train`, `lab.rl` and `lab.flows`. *Gate: Collie's production infrastructure is managed by the stack, and a NeoRx training run executes on a GPU worker from a Prefect flow.*
6. **Weeks 11–12: Adapters.** Spike Dapr pub/sub for two days first. If it holds up, NATS, Kafka and RabbitMQ come through Dapr components; if not, build the native EventBus adapters for all three together. Build and the VectorStore adapters for pgvector, Qdrant and LanceDB, in Python and Go, plus the MongoDB and Neo4j data adapters. A port only counts as proven once at least two adapters pass its contract suite. *Gate: the same Collie event flow and the same RAG pipeline pass their suites on every adapter, switched by config alone.*
7. **Week 13: Second consumers.** Move Domus's frontend onto the registry and its Go backend onto the Go service kit, which must pass heph conform. Point Ligase at `hephkit-core` hashing and `lab.repro` provenance. *Gate: two products and two research repos run on Hephaestus, so cut both the `saas` and `research` templates.*
8. **On demand, entering as experimental:** workflows on Restate or Temporal, agents, MCP, retrieval and memory (likely first with ADAM or Karani), voice (Sonra), serving, the TypeScript (Hono) and Rust (axum) service kits, TypeScript and Rust adapters, Pinecone, Atlas Vector Search and ClickHouse (each with the first project that needs it), cogsci, documents, row-level security helpers and the native kit, each when a project asks for it.

## Decisions

Settled on 4 Nov 2026, including approval of the design.

- [x] **Licence.** Public, MIT.
- [x] **Name.** Hephaestus, with packages published as `hephkit` on PyPI and crates.io and `@hephkit` on npm. Register all three before the first commit.
- [x] **Experiment tracking.** Self-hosted MLflow.
- [x] **Agent runtime.** LangGraph, wrapped with Hephaestus budgets, approvals and tracing.
- [x] **Production observability.** Grafana Cloud over OTLP.
- [x] **Terraform state.** HCP Terraform's free tier.
- [x] **Job queue.** Procrastinate from the start, Collie included. Celery stays available through an adapter when a workload needs it.
- [x] **TypeScript backends.** Hono and Express, both running on Bun, with one service kit covering both.
- [x] **Default layout.** A modular monolith in a monorepo, split into services only when a module needs its own scaling, language or release cadence.
- [x] **Brokers and stores.** Pluggable: NATS JetStream, Kafka or RabbitMQ, chosen per project with NATS as the default. Data stores (relational, document, key-value, graph, analytical) and vector stores (pgvector, Qdrant, LanceDB, Pinecone, Atlas) are pluggable the same way, with Postgres and pgvector as defaults.
- [x] **Approve this design.** Approved 4 Nov 2026. Next: the Phase 1 build plan, then scaffolding the repo.
