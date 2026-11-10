# Docs site

A Nextra 4 app that static-exports to `docs/site/out` (with a Pagefind search
index in `out/_pagefind`). It is served as pre-built files; nothing re-renders at
deploy time.

Every error response from `hephkit` carries
`type: https://hephkit.dev/errors/<code>` (`heph-spec` section 1.4, ADR 0019), so
this site must be reachable at that domain with extensionless URLs.

## Deploying (your own accounts; nobody else can do this)

The repo holds no deploy token and must not. Vercel's Git integration builds
the site on every push, which is the design's choice.

### 1. Create the Vercel project

1. In Vercel, **Add New > Project** and import `Neoforge-Labs/hephaestus`.
2. Set **Root Directory** to the **repo root** (leave it blank or `./`). Do not
   set it to `docs/site`: the workspace declaration and `bun.lock` live at the
   repo root, and a project rooted at `docs/site` cannot install.
3. Leave **Framework Preset**, build command, output directory and install
   command alone. They come from [`/vercel.json`](../../vercel.json), which sets
   framework `null` (not Next.js), install `bunx bun@1.4.4 install --frozen-lockfile`,
   build `bun run --cwd docs/site build`, output `docs/site/out`, and
   `cleanUrls: true` so `/errors/HEPH-MONEY-422` serves
   `out/errors/HEPH-MONEY-422.html`.
4. Set the production branch to `main`.
5. Node and bun versions are pinned in the repo as far as Vercel allows:
   - **Node**: Vercel reads `engines.node` from the root `package.json`
     (`26.x`), which overrides the Node.js Version project setting. Vercel does
     not read `.prototools`. Keep `engines.node` equal to `node` in `.prototools`.
     Vercel offers 26.x, 24.x and 22.x; 26.x is also its default.
   - **Bun, install only**: Vercel's `bunVersion` selects the *Functions*
     runtime, not the build, so it is not used. The install command is pinned
     with `bunx bun@1.4.4 install --frozen-lockfile`, the pattern Vercel's own
     guide gives for pinning Bun in the Install Command. Install is where Bun
     matters: lockfile format, resolution and the root `zod` override. Keep the
     version equal to `bun` in `.prototools`; a test
     (`tools/tests/test_vercel_config.py`) fails if they differ.
   - **Build**: needs no Bun pin. `bun run` only launches the `build` script, and
     `next build` runs under Node (its entry point starts `#!/usr/bin/env node`),
     which `engines.node` pins.
   - Left to project settings: nothing is required. If you change the Node.js
     Version setting, `engines.node` still wins.

### 2. Add the custom domain

The host is `hephkit.dev`, at the apex with no `www` (ADR 0019). Register the
domain first; it is not a subdomain of anything we already own.

1. In the project, **Settings > Domains**, add `hephkit.dev`.
2. At the DNS provider for `hephkit.dev`, add the record Vercel shows. At the
   apex that is an `A` record (or an `ALIAS`/`ANAME` if the provider offers one),
   **not a `CNAME`** — DNS does not allow a CNAME at a zone apex. Use the value
   on the Domains screen; Vercel's apex A record is typically `76.76.21.21`.
3. Wait for Vercel to report the domain as valid and issue the certificate.
   `.dev` is HSTS-preloaded, so the site is unreachable over plain HTTP until
   the certificate exists — a failure before then is expected, not a misconfig.

### 3. Check it

After the first production deploy, these should all return 200:

```
curl -sI https://hephkit.dev/errors/HEPH-MONEY-422
curl -sI https://hephkit.dev/errors
curl -sI https://hephkit.dev/adrs
curl -sI https://hephkit.dev/
```

and `/errors/HEPH-MONEY-422.html` should answer 308 to the extensionless URL.

## Local

```
bun install
bun run --cwd docs/site build
bun test --cwd docs/site
```
