---
# GENERATED FILE - do not edit by hand. Source: docs/adr/0002-mit-licence.md.
# Regenerate with `uv run tools/gen_site_pages.py`; CI runs --check.
title: "0002. Public repository under the MIT licence"
---

# 0002. Public repository under the MIT licence

## Status

Accepted. Date: 2026-11-04.

## Context

Hephaestus is the forge every NeoForge product and research project is built from. NeoForge builds to sell, and a buyer must receive everything needed to run the product. A private dependency they cannot own stalls due diligence. Plumbing is not the moat; products, customers and data are.

## Decision

The repository `Neoforge-Labs/hephaestus` is public and MIT-licensed. Product-specific logic never enters it.

## Consequences

A buyer inherits an MIT dependency with no licence negotiation, so a sale stays clean, and building in public is possible. Everything committed is world-readable, so secrets and code we do not own must never land here. In particular DataQRL and Backbone code is not ours to copy (CLAUDE.md rule 9); only NeoForge and cod3smith repos are harvested. Anyone, including competitors, may reuse the kit.
