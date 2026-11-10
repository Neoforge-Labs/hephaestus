---
# GENERATED FILE - do not edit by hand. Source: docs/adr/0019-the-public-domain-is-hephkit-dev.md.
# Regenerate with `uv run tools/gen_site_pages.py`; CI runs --check.
title: "0019. The public domain is hephkit.dev"
---

# 0019. The public domain is hephkit.dev

## Status

Accepted. Date: 2026-11-10. Design: `docs/superpowers/specs/2026-11-10-hephkit-dev-domain-design.md`.

## Context

Hephaestus is already open source: the repo is public, `LICENSE` is MIT and `CONTRIBUTING.md` exists. What it lacks is a front door. Its only address was `heph.neoforgelabs.tech`, which reads as a company's internal infrastructure. That is wrong for the two things we now want from the kit's address:

1. **A front door.** Somewhere a stranger can land and decide whether to adopt the kit.
2. **A portfolio link.** An address that stands on its own, not as a subdomain of a company site.

The name Hephaestus is crowded. At least six unrelated open-source projects use it, and `hephaestus.dev` is taken, so `hephaestuskit.dev` would still swim in the same pool. `hephkit` is different. It is unique across PyPI, npm, crates.io and every `hephkit.*` domain (checked 2026-11-10), and it is already what a user types: `uv add hephkit`.

The address is about to become expensive to change. `hephkit.errors.TYPE_BASE_URL` puts it in every problem+json body, and `spec/heph-spec.md` section 1.4 makes it a MUST. The `hephkit` 0.1 release publishes that value in a wheel on PyPI, after which changing it is a compatibility event instead of an edit. At the time of this decision the spec was still `0.2.0` Draft, and no conformance vector encodes the host; only the `$id` of `conformance/schema/vector-file.schema.json` does, so there was nothing to regenerate and no vector to correct from our own output.

## Decision

The public host is `hephkit.dev`, at the apex with no `www`.

- The site is `https://hephkit.dev`, error pages are `https://hephkit.dev/errors/<code>`, and the Phase 4 registry is `https://hephkit.dev/r/*.json`.
- `spec/heph-spec.md` section 1.4 now requires `type` to be `https://hephkit.dev/errors/<code>`. The spec moves to `0.3.0`, a minor bump because a MUST changed.
- `hephkit.errors.TYPE_BASE_URL` is `"https://hephkit.dev/errors/"` and stays a module constant: the spec makes it normative, so it is not configurable. The schema `$id` moves to the same host.
- The repo keeps its name. `go/go.mod` declares `github.com/Neoforge-Labs/hephaestus/go`, so renaming the repo would break that module path and every `go install` line. Hephaestus remains the project's name, `hephkit` is how it installs, and `hephkit.dev` is where it lives.
- External adopters are now an audience we address on purpose. The design's reasoning for keeping the kit public and MIT-licensed was a clean sale; this decision adds that a stranger should be able to find the kit and use it. The non-goal that forbade it, "Courting external adopters", was carried by the docs-site design (`docs/superpowers/specs/2026-11-05-docs-site-and-landing-page-design.md`), not the parent design, and this decision reverses it there. The marketing it listed (no SEO campaign, no newsletter, no blog, no testimonials, no pricing) stays out of scope. Tone on the landing page is in scope, and the honest maturity table is not touched: every module stays `experimental`.

## Consequences

The old host is deleted rather than redirected. It never resolved, so there is nothing to redirect. `tools/tests/test_no_stale_domain.py` fails if it reappears in any repo file other than the documents about this move, which name it deliberately.

This had to land before the `hephkit` 0.1 wheel ships. Doing it afterwards would have put the old URL into problem bodies in the wild.

The domain registration and the Vercel project are outside the repo and are done by hand, with an apex A or ALIAS record, since an apex cannot be a CNAME. No deploy token enters the repo. Until the domain is live, the error URLs do not resolve; they are identifiers first and links second.

The cost is a mild mismatch between the `Neoforge-Labs/hephaestus` repo name and the `hephkit.dev` host, and `hephkit` means nothing to a newcomer until the page explains it. `.dev` is HSTS-preloaded, so HTTPS is mandatory on the site.
