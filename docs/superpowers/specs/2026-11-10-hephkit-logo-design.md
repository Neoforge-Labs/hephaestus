# The hephkit mark — short design

**Date:** 2026-11-10
**Status:** approved by Kelyn, 2026-11-10
**Size:** small change (short design; no builder check)
**Sibling design:** `docs/superpowers/specs/2026-11-10-hephkit-dev-domain-design.md`
(the domain; this is the other half of the same front door)
**Touches plan slot:** Phase 1 Task 15 / the docs-site plan's Task 8 (the hero
needs a mark), and Phase 4's brand presets (see "Relationship to brand presets")

## Intent and why

The kit is getting a public address, `hephkit.dev`, and two audiences who have
never seen it: someone deciding whether to adopt it, and someone reading Kelyn's
portfolio. Both form an impression before they read a word. Right now there is
no mark at all — no favicon, no avatar, nothing for the hero or the social card —
so the site would ship as unlabelled text and the GitHub org would keep its
generated identicon.

## Goals

1. One mark that works at 16px and at hero size, on dark and on light.
2. A favicon, an avatar/app icon, and a social card, so the site and the repo
   stop looking anonymous.
3. A palette that is hephkit's own and does not collide with the ingots'.
4. Assets a human can regenerate: plain SVG with the geometry recorded, not an
   exported binary nobody can edit.

## Non-goals

- A full brand system: no type scale, no component tokens, no illustration
  style. Brand presets are Phase 4.
- Renaming or restyling anything that already exists in the repo.
- Animation, a 3D treatment, or a mascot.

## Anti-goals

- **A mark that reads as an AI product.** The four-point symmetrical sparkle is
  the single thing this mark must not be mistaken for. A version that needs a
  caption to avoid that reading has failed even if it is pretty.
- A mark that only works at hero size. If the favicon has to be a different
  drawing, that is fine — but it must be drawn, not scaled and hoped for.
- Anything that implies the kit is more mature than `experimental`.

## Constraints

- **Green is excluded.** `#4ade80 on #0a0a0a` belongs to Domus and `#0E6944` to
  NeoHealth (parent design, line 352). The forge should not wear the colours of
  the things it casts.
- **`#C2884A` reaches only 3.0:1 on white**, so it cannot be the light-background
  colour. Light backgrounds use `#8A5A24` (5.9:1). Measured, not estimated.
- **Negative space closes at small sizes.** The spark is a hole, and holes fill
  in first. This forces a separate favicon cut (see "Decided").
- Nextra's own type is the site's type; the wordmark must not require a new font
  download.

## Approaches

Four rounds in the browser on 2026-11-10; Kelyn picked at each step.

**Round 1 — what the mark is about.** Ingot (the repo's own word for what the
forge casts), anvil (the literal object), glyph (`h` with a block cursor), strike
(the moment of forging). My recommendation was the ingot, on the grounds that it
came from vocabulary the project already owned. **Kelyn picked the strike**, and
the browser events show no hesitation — six clicks on it and none on anything
else. Recorded because the reasoning that follows is built on his pick, not mine.

**Round 2 — beating the sparkle problem.** The strike's one real weakness is
that a four-point spark now reads as "AI product". Four fixes, each attacking a
different part of the resemblance: asymmetry, negative space, a six-point count,
and the struck bar for context. **Picked: negative space** — the strike punched
out of a solid block, which is the only one that cannot be misread at any size,
because a hole is categorically not a glint.

**Round 3 — palette.** Ember (`#EA580C`), white-hot (monochrome plus a pale heat
accent), iron and sky (slate and cyan), bronze. **Picked: bronze.** It keeps the
forge story, avoids the crowded bright-orange space in dev tooling, and the
contrast check knocked out ember's main virtue anyway: white text fails on
`#EA580C` at 3.55:1.

**Round 4 — wordmark.** Geometric sans versus monospace. **Picked: sans.** Mono
flatters the adopter audience but not the portfolio one, and the mark already
carries the forge meaning, so the type's job is to stay out of the way.

## Decided

**The mark.** A four-point strike knocked out of a rounded square, `viewBox
"0 0 96 96"`:

- plate: `<rect x="10" y="10" width="76" height="76" rx="18">`
- strike, masked out: `M48 18 L55 41 L78 48 L55 55 L48 78 L41 55 L18 48 L41 41 Z`

**The palette.**

| Token | Hex | Use |
| --- | --- | --- |
| `ink` | `#0C0A09` | dark background |
| `bronze` | `#C2884A` | the mark on dark; accents on dark |
| `bronze-deep` | `#8A5A24` | the mark on light; any bronze carrying light text |
| `paper` | `#F5F0E8` | light background |

**The wordmark.** Lowercase `hephkit`, geometric sans, tracking about `-0.03em`,
weight 700. The site uses Nextra's own sans; no font is added. `.dev` is not part
of the lockup — the wordmark is the package name, and the domain is where it
lives, not what it is called.

**Three drawings, not one scaled drawing** (my call, from what the size strip
showed):

1. **Primary** — the mask above, for hero, README and anything 24px and up.
2. **Favicon** — the same composition with a visibly fatter strike cut, hand-tuned
   so it still reads at 16px. It is a sibling drawing, not a transform.
3. **Avatar / app icon** — inverted: a solid bronze tile with a dark strike, for
   the GitHub org avatar and any touch icon. Shrinking the primary is not an
   acceptable substitute.

**Where the files live** (my call): `docs/site/public/brand/`. It is the only
place that must serve them over HTTP, Nextra serves `public/` as-is, and the
README can reference the same paths relatively — so there is one copy and no
sync step, which the repo's rule against hand-edited synced files would
otherwise make awkward.

**No maturity label and no ADR.** Brand assets are not a capability with a spec
or a contract suite, so the maturity rule does not apply to them; stating this
so a reviewer does not read its absence as an omission. No recorded decision is
reversed, so no ADR — unlike the domain, which needs one.

## Relationship to brand presets

Phase 4 ships brand presets as token sets, and this adds a fifth alongside
Collie, Domus, NeoHealth and NeoForge. The principle behind the green exclusion —
**the forge does not wear the colours of its ingots** — is a constraint on every
future preset, not just this one. It is recorded here rather than as an ADR
because nothing is being reversed. If it should bind the registry, it wants
promoting to an ADR when Phase 4 starts; that is Kelyn's call, not the builder's.

## Left to the builder

- The exact fatter cut for the 16px favicon. It is a drawing judgement made by
  looking at it at 16px, not a formula.
- The corner radius once the mark is seen outside a mockup; `rx="18"` of 76 is a
  starting point, not a measured decision.
- Social-card composition at 1200×630, and whether it carries the hero's command
  line or only the lockup.
- Which raster sizes to commit (`apple-touch-icon` at 180 is needed; beyond that,
  what the site actually references) and whether a `.ico` is worth shipping at
  all given SVG favicon support.
- Whether the mark gets `fill="currentColor"` with the colour set by CSS, or
  ships as explicit per-background variants. Two files is probably simpler than
  one clever one, but the builder should look at how the hero uses it first.
