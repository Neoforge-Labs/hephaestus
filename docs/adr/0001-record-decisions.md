# 0001. Record decisions as ADRs

## Status

Accepted. Date: 2026-11-04.

## Context

The design (`docs/superpowers/specs/2026-11-04-hephaestus-design.md`) settled a set of decisions on 4 Nov 2026. A solo operator and future contributors, or a buyer doing due diligence, need to see why each was made, not only what the code does.

## Decision

Each decision becomes a numbered ADR in `docs/adr/`, starting with the ones settled on 4 Nov 2026. ADRs use the Status, Context, Decision, Consequences format from `0000-template.md`. An accepted ADR is never edited; a changed decision is recorded as a new ADR that supersedes the old one.

## Consequences

The reasoning behind the kit stays in the repo and survives turnover. `tools/check_adrs.py` enforces contiguous four-digit numbering and the required headings in CI, so the record cannot silently rot. Changing a decision costs an extra document, which is the point: behaviour changes also need the spec and conformance vectors updated in the same PR (CLAUDE.md rule 1).
