# syntax=docker/dockerfile:1
# ghcr.io/neoforge-labs/heph-python — Python runtime base for Hephaestus services.
# Maturity: experimental.
#
# Base images are pinned by digest so a rebuild cannot silently pick up a
# different upstream. The tag in each comment says what the digest refers to;
# to bump, resolve the new digest (docker buildx imagetools inspect <tag>) and
# change the tag comment and digest together.
#
# PYTHON_VERSION tracks a newer runtime than the project floor (>=3.12): the
# abi3-py312 wheels run unchanged on 3.13. If you override PYTHON_VERSION you
# must also override PYTHON_DIGEST and PYTHON_FULL_VERSION. The build stage
# asserts that the interpreter the digest provides matches all three, so a
# mismatch fails the build instead of shipping the wrong runtime or a wrong
# PYTHON_VERSION variable (a digest wins over a tag; Docker ignores the mismatch).

ARG PYTHON_VERSION=3.13
# python:3.13-slim-bookworm (multi-arch index digest)
ARG PYTHON_DIGEST=sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f
# Exact version that digest provides; becomes the PYTHON_VERSION env var.
ARG PYTHON_FULL_VERSION=3.13.18

# --- Stage 1: uv -------------------------------------------------------------
# uv ships as a static binary; take it from the official image rather than
# installing pip + a toolchain into the runtime layer.
# ghcr.io/astral-sh/uv:0.13.7
FROM ghcr.io/astral-sh/uv@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

# --- Stage 2: build ----------------------------------------------------------
# Patch, create the user, and strip what a uv-managed runtime never uses. This
# happens in its own stage and is copied across as ONE layer, because deleting
# files in a later layer would not shrink the image (budget: 250 MB).
FROM python:${PYTHON_VERSION}-slim-bookworm@${PYTHON_DIGEST} AS build

# Re-declared: a global ARG is not visible inside a stage until it is.
ARG PYTHON_VERSION
ARG PYTHON_FULL_VERSION

# Invariant: the requested version, the restated ENV value and the interpreter the
# digest actually provides must agree. Enforced here so it cannot drift.
RUN actual="$(python3 -c 'import platform; print(platform.python_version())')" \
 && case "$actual" in "${PYTHON_VERSION}".*) ;; \
      *) echo "PYTHON_VERSION=${PYTHON_VERSION} but the pinned digest provides ${actual}" >&2; exit 1 ;; esac \
 && [ "$actual" = "${PYTHON_FULL_VERSION}" ] \
 || { echo "PYTHON_FULL_VERSION=${PYTHON_FULL_VERSION} but the pinned digest provides ${actual}" >&2; exit 1; }

# Pick up Debian security fixes published since the pinned base was built. This
# makes rebuilds not bit-reproducible, deliberately: a base image that never
# patches is worse than one that is not bit-reproducible. Drift is handled by the
# digest pin plus a scan on every CI build. Do not remove this as an oversight.
# Then create the unprivileged user. No recommends; apt lists removed.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/* \
 && groupadd --gid 10001 heph \
 && useradd --uid 10001 --gid heph --create-home --shell /usr/sbin/nologin heph \
 && mkdir -p /app \
 && chown heph:heph /app

# uv replaces pip/setuptools/wheel, and a service image has no use for IDLE,
# tkinter, the test suite or turtle demos. Remove them (and only them). Also
# drop setuid/setgid bits: nothing in a service image should escalate, and the
# unprivileged user never needs to.
RUN set -eux; \
    py="/usr/local/lib/python${PYTHON_VERSION}"; \
    rm -rf "$py/site-packages"/* "$py/ensurepip" "$py/idlelib" "$py/test" \
           "$py/tkinter" "$py/turtledemo" "$py/turtle.py" \
           "$py"/lib-dynload/_tkinter*.so "$py"/lib-dynload/_test*.so \
           /usr/local/bin/pip* /usr/local/bin/idle* /usr/local/bin/pydoc* \
           /usr/local/bin/2to3* /usr/local/share/man; \
    find /usr/local -type d -name __pycache__ -path '*/test/*' -prune -exec rm -rf {} +; \
    find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec chmod ug-s {} +

COPY --from=uv /uv /usr/local/bin/uv

# --- Stage 3: runtime --------------------------------------------------------
# WHY THIS IS `FROM scratch`: it flattens the prepared filesystem into one layer
# so the stripping in stage 2 actually shrinks the image (deletions in a later
# layer do not). Without it the image is ~273 MB, over the 250 MB budget. Do not
# "simplify" this back to `FROM python:...`. The cost is that upstream ENV and
# labels are lost, which is why they are restated below.
FROM scratch AS runtime
ARG PYTHON_FULL_VERSION
COPY --from=build / /

LABEL org.opencontainers.image.title="heph-python" \
      org.opencontainers.image.description="Hephaestus Python base image" \
      org.opencontainers.image.source="https://github.com/neoforge-labs/hephaestus" \
      org.opencontainers.image.vendor="NeoForge Labs" \
      dev.neoforge.heph.maturity="experimental"

# FROM scratch drops the upstream image's ENV, so the ones Python needs are
# restated here (same values as the pinned python:3.13-slim-bookworm image).
# PYTHON_VERSION is the full upstream version, taken from PYTHON_FULL_VERSION,
# which the build stage verifies against the installed interpreter. (The build
# ARG of the same name is only the minor.) GPG_KEY and PYTHON_SHA256 are
# build-time-only upstream values and are not restated.
ENV PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8 \
    PYTHON_VERSION=${PYTHON_FULL_VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1

WORKDIR /app
USER 10001:10001
CMD ["python3"]

# No HEALTHCHECK: a base image cannot know what "healthy" means for the service
# built on top of it. Services define their own.
