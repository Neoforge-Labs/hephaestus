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

**The config in this repo cannot deploy itself.** Until the steps below are
done, merging to `main` builds nothing and the error URLs 404 — there is no
signal in the repo that anything is missing, because nothing in the repo is.
To check from outside Vercel whether the integration is live at all:

```
gh api orgs/Neoforge-Labs/installations --jq '[.installations[].app_slug]'
```

`vercel` must appear in that list, and `gh api repos/Neoforge-Labs/hephaestus/deployments --jq length`
must be greater than zero once a build has run. Both being empty means no push
has ever reached Vercel.

### 1. Create the Vercel project

1. The repo is owned by the **Neoforge-Labs organization**, not a personal
   account, so Vercel's GitHub App has to be installed on that org and granted
   access to `hephaestus` (Vercel offers this during the import; an org owner
   has to approve it). A personal Vercel account cannot import an org repo it
   has not been given.
2. In Vercel, **Add New > Project** and import `Neoforge-Labs/hephaestus`.
3. Set **Root Directory** to the **repo root** (leave it blank or `./`). Do not
   set it to `docs/site`: the workspace declaration and `bun.lock` live at the
   repo root, and a project rooted at `docs/site` cannot install.
4. Leave **Framework Preset**, build command, output directory and install
   command alone. They come from [`/vercel.json`](../../vercel.json), which sets
   framework `null` (not Next.js), install `bunx bun@1.4.4 install --frozen-lockfile`,
   build `bun run --cwd docs/site build`, output `docs/site/out`, and
   `cleanUrls: true` so `/errors/HEPH-MONEY-422` serves
   `out/errors/HEPH-MONEY-422.html`.
5. Set the production branch to `main`.
6. Node and bun versions are pinned in the repo as far as Vercel allows:
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

The host is `hephkit.dev`, at the apex with no `www` (ADR 0019). The domain is
registered and its nameservers are Cloudflare's (`dig NS hephkit.dev`), so the
records below are added in Cloudflare, not in Vercel.

1. In the project, **Settings > Domains**, add `hephkit.dev`.
2. In Cloudflare's DNS tab for `hephkit.dev`, add an **`A`** record at the apex
   (name `@`) with the value Vercel's own Domains screen shows for *this*
   project. Do not copy an address from another project or from a blog: Vercel's
   DNS documentation says projects can be assigned different addresses. A
   `CNAME` is not valid at a zone apex, which needs `NS` and `SOA` records.
3. **Set the record's proxy status to "DNS only" (grey cloud), not "Proxied".**
   This is the one step that fails silently. A proxied record answers DNS
   queries with Cloudflare's own addresses, so Vercel cannot confirm the record
   or complete certificate validation, and the domain sits on **Invalid
   Configuration** while `dig A hephkit.dev` returns addresses that look fine
   but are not Vercel's.
4. Two records that break it if they exist: any **`AAAA`** at the apex (Vercel
   does not serve custom domains over IPv6, so an AAAA splits traffic and can
   stall certificate issuance), and any **`CAA`** that does not permit Let's
   Encrypt — if the zone has CAA records at all, one must be
   `0 issue "letsencrypt.org"`.
5. Wait for Vercel to report the domain as valid and issue the certificate.
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
