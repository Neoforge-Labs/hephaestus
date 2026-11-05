# syntax=docker/dockerfile:1
# ghcr.io/neoforge-labs/heph-node — Node runtime base for Hephaestus web services.
# Maturity: experimental.
#
# Node 26 is the current Active LTS (matches .prototools). Pinned by digest so a
# rebuild cannot silently pick up a different upstream. To bump, resolve the new
# digest (docker buildx imagetools inspect <tag>) and change the tag comment and
# digest together.
#
# This is a RUNTIME image: it runs `node server.js` (Next.js standalone output).
# It deliberately ships WITHOUT npm/npx (and without Node headers). `RUN npm ci`
# on top of `FROM heph-node` will fail with "npm: not found". Builds belong in a
# builder stage (e.g. node:26) or in CI; copy the built output into this image.
# Keeping npm out removes a package manager and its bundled dependency tree (six
# fixable HIGH CVEs at the time of writing) from every service image.

ARG NODE_VERSION=26
# node:26-bookworm-slim (multi-arch index digest)
ARG NODE_DIGEST=sha256:c3aea913c1a6c89c0daf1e94867118e4aae4846b2c58c8cb9b33b80c5c695b8d
# Exact version that digest provides; becomes the NODE_VERSION env var.
ARG NODE_FULL_VERSION=26.13.0

# --- Stage 1: build ----------------------------------------------------------
# Patch, create the user, and strip what a runtime never uses. This happens in
# its own stage and is copied across as ONE layer, because deleting files in a
# later layer would not shrink the image.
FROM node:${NODE_VERSION}-bookworm-slim@${NODE_DIGEST} AS build

# Re-declared: a global ARG is not visible inside a stage until it is.
ARG NODE_VERSION
ARG NODE_FULL_VERSION

# Invariant: the requested major, the restated ENV value and the node the digest
# actually provides must agree (a digest wins over a tag; Docker ignores the
# mismatch). Enforced here so it cannot drift.
RUN actual="$(node --version)" \
 && case "$actual" in "v${NODE_VERSION}".*) ;; \
      *) echo "NODE_VERSION=${NODE_VERSION} but the pinned digest provides ${actual}" >&2; exit 1 ;; esac \
 && [ "$actual" = "v${NODE_FULL_VERSION}" ] \
 || { echo "NODE_FULL_VERSION=${NODE_FULL_VERSION} but the pinned digest provides ${actual}" >&2; exit 1; }

# Pick up Debian security fixes published since the pinned base was built. This
# makes rebuilds not bit-reproducible, deliberately: a base image that never
# patches is worse than one that is not bit-reproducible. Drift is handled by the
# digest pin plus a scan on every CI build. Do not remove this as an oversight.
# Then create the unprivileged user. The upstream "node" user is uid 1000; Hephaestus
# images use 10001 everywhere. No recommends; apt lists removed.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/* \
 && groupadd --gid 10001 heph \
 && useradd --uid 10001 --gid heph --create-home --shell /usr/sbin/nologin heph \
 && mkdir -p /app \
 && chown heph:heph /app

# No npm/npx (see header), no Node headers or changelog (a runtime never compiles
# native addons), and no setuid/setgid binaries: nothing in a service image
# should be able to escalate, and the unprivileged user never needs to.
RUN rm -rf /usr/local/lib/node_modules /usr/local/bin/npm /usr/local/bin/npx \
           /usr/local/include /usr/local/CHANGELOG.md \
 && find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec chmod ug-s {} +

# --- Stage 2: runtime --------------------------------------------------------
# WHY THIS IS `FROM scratch`: it flattens the prepared filesystem into one layer
# so the removals in stage 1 actually shrink the image (deletions in a later
# layer do not). Do not "simplify" this back to `FROM node:...`. The cost is that
# upstream ENV, ENTRYPOINT, CMD and labels are lost, which is why they are
# restated below.
FROM scratch AS runtime
ARG NODE_FULL_VERSION
COPY --from=build / /

LABEL org.opencontainers.image.title="heph-node" \
      org.opencontainers.image.description="Hephaestus Node base image (Next.js standalone-ready)" \
      org.opencontainers.image.source="https://github.com/neoforge-labs/hephaestus" \
      org.opencontainers.image.vendor="NeoForge Labs" \
      dev.neoforge.heph.maturity="experimental" \
      dev.neoforge.heph.node.no-npm="npm and npx are not installed; build in a builder stage or CI"

# FROM scratch drops the upstream image's ENV, ENTRYPOINT and CMD, so they are
# restated (same values as node:26-bookworm-slim), plus the Next.js standalone
# settings: it reads PORT and HOSTNAME, and binds to the container hostname
# unless told otherwise, which is unreachable from outside the container.
# NODE_VERSION comes from NODE_FULL_VERSION, which the build stage verifies
# against the installed node.
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    NODE_VERSION=${NODE_FULL_VERSION} \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /app
USER 10001:10001
EXPOSE 3000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["node"]

# No HEALTHCHECK: a base image cannot know what "healthy" means for the service
# built on top of it. Services define their own.
