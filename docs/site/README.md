# Docs site

A Nextra 4 app that static-exports to `docs/site/out` (with a Pagefind search
index in `out/_pagefind`). It is served as pre-built files; nothing re-renders at
deploy time.

Every error response from `hephkit` carries
`type: https://heph.neoforgelabs.tech/errors/<code>` (`heph-spec` section 1.4), so
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
   framework `null` (not Next.js), install `bun install --frozen-lockfile`,
   build `bun run --cwd docs/site build`, output `docs/site/out`, and
   `cleanUrls: true` so `/errors/HEPH-MONEY-422` serves
   `out/errors/HEPH-MONEY-422.html`.
4. Set the production branch to `main`.
5. Check **Node.js Version** under Settings > General. `.prototools` pins node
   26 and Vercel does not read it; choose the newest version it offers that
   builds cleanly.

### 2. Add the custom domain

1. In the project, **Settings > Domains**, add `heph.neoforgelabs.tech`.
2. At the DNS provider for `neoforgelabs.tech`, add the record Vercel shows. For
   a subdomain that is a `CNAME` named `heph` pointing at the target Vercel gives
   you (typically `cname.vercel-dns.com`). Use the value on the Domains screen if
   it differs.
3. Wait for Vercel to report the domain as valid and issue the certificate.

### 3. Check it

After the first production deploy, these should all return 200:

```
curl -sI https://heph.neoforgelabs.tech/errors/HEPH-MONEY-422
curl -sI https://heph.neoforgelabs.tech/errors
curl -sI https://heph.neoforgelabs.tech/
```

and `/errors/HEPH-MONEY-422.html` should answer 308 to the extensionless URL.

## Local

```
bun install
bun run --cwd docs/site build
bun test --cwd docs/site
```
