# 0015. Maturity levels for every module

## Status

Accepted. Date: 2026-11-04.

## Context

Full scope is safe only if breadth cannot leak unproven code into production, especially on money paths.

## Decision

Every module, kit and adapter carries one label, shown on its docs page and checked by `heph doctor`. `experimental`: API may change, not for production; no promotion requirement. `beta`: API settled, usable in production off the money path; requires passing its contract suite, docs with a runnable example, and use by one ingot. `stable`: covered by semver and the deprecation policy; requires the coverage gate met, use by two ingots in production, and passing ecosystem CI. New work starts `experimental`. Money, ledger, idempotency and webhook modules can only be used in a production money path once `stable`, and `heph doctor` fails a deploy that breaks this rule.

## Consequences

Breadth is allowed without risking production. Everything in Phase 1 ships labelled `experimental`, so none of it may sit in a production money path yet. Promotion needs real consumers, which creates a deliberate dependency on the ingots using each module. `heph doctor` must implement the check.
