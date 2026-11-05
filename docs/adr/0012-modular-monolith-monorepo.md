# 0012. Modular monolith in a monorepo by default

## Status

Accepted. Date: 2026-11-04.

## Context

Projects range from one backend plus one frontend to eight services behind Traefik. Hephaestus must make neither choice force a rewrite, and a solo operator should not pay microservice costs before they are earned.

## Decision

The default layout is a modular monolith in a monorepo, with uv, pnpm, Cargo and Go workspaces side by side. Modules talk only through their contracts; import boundaries are enforced with import-linter in Python and `internal/` packages in Go. A module is split into its own service only when it needs its own scaling, language or release cadence. Events use the same schemas and outbox through an in-process bus in the monolith and a broker in a service layout. `heph new` takes `--layout monolith|services`.

## Consequences

Splitting a module out is a deployment change, not a rewrite, because the boundary is its contract. Cross-module calls must be disciplined from day one. A service can still move to its own repo later.
