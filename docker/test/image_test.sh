#!/usr/bin/env bash
# Usage: image_test.sh IMAGE [RUNTIME]
# Asserts the base-image contract for heph-python and heph-node:
#   - default user is uid 10001, workdir /app is writable by it
#   - the runtime tool exists (uv + python for python, node for node) and agrees
#     with the image's own *_VERSION env var
#   - /var/lib/dpkg/status is present and non-trivial (SBOM/scan prerequisite)
#   - heph-node's real ENTRYPOINT works
#   - heph-python is under 250 MB
# RUNTIME (python|node) is derived from the repository name of IMAGE
# (heph-python / heph-node, ignoring registry and tag) unless given explicitly,
# e.g. to run the suite against a stock image.
set -uo pipefail

IMAGE="${1:?usage: image_test.sh IMAGE [python|node]}"

# Decimal megabytes (what `docker image inspect` reports in bytes / 1e6). This is
# deliberately stricter than 250 MiB (262,144,000 bytes); do not "correct" it to MiB.
MAX_PYTHON_BYTES=$((250 * 1000 * 1000))
# A real dpkg status database for these images is tens of KB; anything below this
# means the package list scanners and SBOM tools rely on is missing or gutted.
MIN_DPKG_STATUS_BYTES=10000
fail=0

check() { # name, ok(0/1), detail
  if [ "$2" -eq 0 ]; then echo "PASS  $1"; else echo "FAIL  $1: $3"; fail=1; fi
}

if [ -n "${2:-}" ]; then
  RUNTIME="$2"
else
  repo="${IMAGE##*/}"; repo="${repo%%@*}"; repo="${repo%%:*}"
  case "$repo" in
    heph-python) RUNTIME=python ;;
    heph-node) RUNTIME=node ;;
    *) echo "FAIL  cannot infer runtime from repository '$repo' (pass python|node as 2nd arg)"; exit 1 ;;
  esac
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "FAIL  image $IMAGE not found"
  exit 1
fi

# Entrypoint is cleared so most checks do not depend on the image's default command.
run() { docker run --rm --entrypoint "" "$IMAGE" "$@"; }

uid="$(run id -u 2>&1 || true)"
[ "$uid" = "10001" ]; check "default uid is 10001" $? "got '$uid'"

wd="$(run pwd 2>&1 || true)"
[ "$wd" = "/app" ]; check "workdir is /app" $? "got '$wd'"

out="$(run sh -c 'touch /app/.w && rm /app/.w && echo ok' 2>&1 || true)"
[ "$out" = "ok" ]; check "/app writable by default user" $? "got '$out'"

dpkg_bytes="$(run sh -c 'wc -c < /var/lib/dpkg/status' 2>&1 | tr -d ' ' || true)"
case "$dpkg_bytes" in *[!0-9]*|"") dpkg_bytes=0 ;; esac
[ "$dpkg_bytes" -ge "$MIN_DPKG_STATUS_BYTES" ]
check "/var/lib/dpkg/status present and non-trivial ($dpkg_bytes bytes)" $? "need >= $MIN_DPKG_STATUS_BYTES bytes"

case "$RUNTIME" in
  python)
    out="$(run uv --version 2>&1)"; rc=$?
    check "uv --version succeeds ($out)" $rc "$out"
    out="$(run python --version 2>&1)"; rc=$?
    check "python --version succeeds ($out)" $rc "$out"
    want="Python $(run sh -c 'echo "$PYTHON_VERSION"' 2>&1)"
    [ "$out" = "$want" ]; check "python agrees with image PYTHON_VERSION" $? "'$out' vs '$want'"
    size="$(docker image inspect "$IMAGE" --format '{{.Size}}')"
    [ "$size" -lt "$MAX_PYTHON_BYTES" ]
    check "size under 250 MB ($((size / 1000000)) MB)" $? "$size bytes"
    ;;
  node)
    out="$(run node --version 2>&1)"; rc=$?
    check "node --version succeeds ($out)" $rc "$out"
    want="v$(run sh -c 'echo "$NODE_VERSION"' 2>&1)"
    [ "$out" = "$want" ]; check "node agrees with image NODE_VERSION" $? "'$out' vs '$want'"
    # Through the image's real ENTRYPOINT (docker-entrypoint.sh), not bypassed.
    out="$(docker run --rm "$IMAGE" node -e 'console.log("entrypoint-ok")' 2>&1 || true)"
    [ "$out" = "entrypoint-ok" ]; check "real ENTRYPOINT runs node" $? "got '$out'"
    ;;
  *)
    check "runtime is python or node" 1 "got '$RUNTIME'"
    ;;
esac

exit $fail
