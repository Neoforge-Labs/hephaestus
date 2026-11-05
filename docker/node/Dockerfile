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
# It deliberately ships without npm/npx. Install and build in a builder stage
# (node:26 or similar) and copy the result in. Keeping npm out removes a
# package manager and its bundled dependency tree from every service image.

ARG NODE_VERSION=26
# node:26-bookworm-slim (multi-arch index digest)
ARG NODE_DIGEST=sha256:c3aea913c1a6c89c0daf1e94867118e4aae4846b2c58c8cb9b33b80c5c695b8d

# --- Stage 1: build ----------------------------------------------------------
# Patch, create the user, and strip what a runtime never uses. This happens in
# its own stage and is copied across as ONE layer, because deleting files in a
# later layer would not shrink the image.
FROM node:${NODE_VERSION}-bookworm-slim@${NODE_DIGEST} AS build

# Pick up Debian security fixes published since the pinned base was built, then
# create the unprivileged user. The upstream "node" user is uid 1000; Hephaestus
# images use 10001 everywhere. No recommends; apt lists removed.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/* \
 && groupadd --gid 10001 heph \
 && useradd --uid 10001 --gid heph --create-home --shell /usr/sbin/nologin heph \
 && mkdir -p /app \
 && chown heph:heph /app

# No npm/npx (see header), and no setuid/setgid binaries: nothing in a service
# image should be able to escalate, and the unprivileged user never needs to.
RUN rm -rf /usr/local/lib/node_modules /usr/local/bin/npm /usr/local/bin/npx \
 && find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec chmod ug-s {} +

# --- Stage 2: runtime --------------------------------------------------------
# Flatten the prepared filesystem into a single layer.
FROM scratch AS runtime
COPY --from=build / /

LABEL org.opencontainers.image.title="heph-node" \
      org.opencontainers.image.description="Hephaestus Node base image (Next.js standalone-ready)" \
      org.opencontainers.image.source="https://github.com/neoforge-labs/hephaestus" \
      org.opencontainers.image.vendor="NeoForge Labs" \
      dev.neoforge.heph.maturity="experimental"

# FROM scratch drops the upstream image's ENV, ENTRYPOINT and CMD, so they are
# restated (same values as node:26-bookworm-slim), plus the Next.js standalone
# settings: it reads PORT and HOSTNAME, and binds to the container hostname
# unless told otherwise, which is unreachable from outside the container.
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
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
