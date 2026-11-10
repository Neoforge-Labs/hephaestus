# hephkit.dev — the public domain, and a front door — short design

**Date:** 2026-11-10
**Status:** approved by Kelyn, 2026-11-10
**Size:** small change (short design; no builder check)
**Parent design:** `docs/superpowers/specs/2026-11-04-hephaestus-design.md` (lines 140, 146)
**Blocks:** `docs/superpowers/plans/2026-11-05-docs-site-and-landing-page.md` Task 1
(the `0.1` release), because the release bakes the URL into a published wheel

## Intent and why

Hephaestus is already open source — the repo is public, `LICENSE` is MIT and
`CONTRIBUTING.md` exists. What it does not have is a front door. Its only
address, `heph.neoforgelabs.tech`, reads as a company's internal infrastructure,
which is wrong for two things Kelyn now wants from it: somewhere a stranger can
land and decide to use the kit, and a link that stands on its own in a
portfolio.

The address is also about to become expensive. `hephkit.errors.TYPE_BASE_URL`
ships it in every problem+json body, `spec/heph-spec.md` §1.4 makes it a MUST,
and plan Task 1 publishes `hephkit` `0.1` to PyPI. Once that wheel is out, the
URL is in the wild and changing it is a compatibility event instead of an edit.
This change lands first or it gets much dearer.

## Goals

1. The kit answers at `https://hephkit.dev`, and `/errors/<code>` resolves there.
2. The old address appears nowhere in the repo when this is done.
3. A stranger who finds a bug or a vulnerability can see where to report it.
4. The record says why the name changed, so the next reader does not re-litigate it.

## Non-goals

- Renaming the repo, the Go module path, or any published package name.
- Marketing: no SEO, no newsletter, no blog, no testimonials, no pricing. The
  landing page's job is still to be honest and legible, not to sell.
- A `CODE_OF_CONDUCT.md` or `CITATION.cff` (see "Decided" below).
- Redirecting the old hostname. It has never been live.

## Anti-goals

- A site that oversells maturity. Every module is `experimental`; the page says
  so. A front door that hides the maturity table would be a failure even if it
  shipped.
- Any hand-maintained copy of the domain. It is one constant in Python and one
  `$id` in a schema, not a string sprinkled through the codebase.

## Constraints

- **`spec/heph-spec.md` §1.4 is a MUST**, so per `CLAUDE.md` rule 1 the spec and
  the vectors change in the same PR as the code, with an ADR because a recorded
  decision changes. No conformance vector encodes the domain — only
  `conformance/schema/vector-file.schema.json`'s `$id` does — so there is
  nothing to regenerate and no vector to "fix" from our own output (rule 2 is
  untouched).
- **The spec is `0.2.0`, Status: Draft.** Changing a MUST pre-1.0 is an ordinary
  edit, not a break.
- **`go/go.mod` declares `module github.com/Neoforge-Labs/hephaestus/go`.**
  Renaming the repo would break that path and every `go install` line in the
  docs. The repo name is load-bearing; the domain is not.
- Kelyn registers `hephkit.dev` and creates the Vercel project. Nobody else can,
  and no deploy token enters this repo.

## Approaches

Three were on the table; Kelyn picked A on 2026-11-10.

| | Approach | Trades off |
|---|---|---|
| **A (picked)** | `hephkit.dev` — the install name becomes the public name | Unique across PyPI, npm, crates.io and every `hephkit.*` domain (checked 2026-11-10); it is already what you type (`uv add hephkit`). `.dev` is HSTS-preloaded, so HTTPS is not optional. Cost: a mild mismatch with the `Neoforge-Labs/hephaestus` repo name, and `hephkit` means nothing to a newcomer until the page explains it |
| B | `hephaestuskit.dev`, keeping Hephaestus in front | Longer to type, and still swims in a crowded pool: at least six unrelated open-source projects are called Hephaestus, and `hephaestus.dev` is taken. Worse for the portfolio goal, which wants a name that is searchable |
| C | Stay on `heph.neoforgelabs.tech` | No spec churn at all. But it reads as internal infrastructure under a company domain, which defeats both reasons for doing this |

## Decided

- **Apex, no `www`.** Site at `https://hephkit.dev`, error pages at
  `https://hephkit.dev/errors/<code>`, Phase 4 registry at
  `https://hephkit.dev/r/*.json`.
- **The repo keeps its name.** Hephaestus stays the project's name and the
  etymology; `hephkit` is how it installs; `hephkit.dev` is where it lives.
- **The old hostname is deleted, not redirected** — it never resolved.
- **ADR 0019** records both the domain and the reversal of the parent design's
  "courting external adopters" non-goal, since the second is the reason for the
  first. One ADR, because they are one decision.
- **Light hygiene only** (Kelyn's call, 2026-11-10): add `SECURITY.md` and
  GitHub issue and PR templates. A kit whose pitch is money correctness needs a
  private channel for vulnerability reports, and templates make a drive-by bug
  report usable. Skip `CODE_OF_CONDUCT.md` until there is a second contributor,
  and `CITATION.cff` belongs to the research ingots, not here.
- **Landing-page tone is in scope, copy rewriting is not.** The non-goal that
  forbade courting adopters goes; the honest maturity table and the
  roadmap-stays-visible rule stay exactly as the docs-site design has them.

## Files this touches

Nine occurrences in six files, plus the new ones:

| File | What |
| --- | --- |
| `spec/heph-spec.md` | §1.4 MUST, and the example body (×2) |
| `python/hephkit/src/hephkit/errors/__init__.py` | `TYPE_BASE_URL` |
| `python/hephkit/tests/test_errors.py` | `TYPE_BASE` |
| `conformance/schema/vector-file.schema.json` | `$id` |
| `docs/superpowers/specs/2026-11-04-hephaestus-design.md` | lines 140, 146; the non-goal |
| `docs/superpowers/plans/2026-11-04-phase-1-core-and-local-stack.md` | lines 20, 191 |
| `docs/adr/0019-*.md` | new |
| `SECURITY.md`, `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md` | new |
| `README.md` | the "Where to look" table gains the site |

The docs-site design and plan (`2026-11-05-*`) also carry the old host and are
updated in the same pass, as is their `vercel.json` CNAME note.

## Left to the builder

- Whether the spec's version bumps to `0.2.1` or `0.3.0`, and the wording of its
  "Decisions this version settles" entry.
- `SECURITY.md`'s reporting channel and response window, and whether it points
  at GitHub private vulnerability reporting or an address.
- The issue-template set: how many, and which fields.
- Whether `TYPE_BASE_URL` stays a module constant or becomes configurable. It is
  a constant today and the spec makes it normative, so it probably stays one —
  but the builder should say so out loud rather than leave it implied.
