#!/usr/bin/env bash
# Usage: image_test.sh IMAGE
# Asserts the base-image contract for heph-python and heph-node:
#   - default user is uid 10001, workdir /app is writable by it
#   - the runtime tool exists (uv for python, node for node)
#   - heph-python is under 250 MB
set -uo pipefail

IMAGE="${1:?usage: image_test.sh IMAGE}"
MAX_PYTHON_BYTES=$((250 * 1000 * 1000))
fail=0

check() { # name, ok(0/1), detail
  if [ "$2" -eq 0 ]; then echo "PASS  $1"; else echo "FAIL  $1: $3"; fail=1; fi
}

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "FAIL  image $IMAGE not found"
  exit 1
fi

# Entrypoint is cleared so the checks do not depend on the image's default command.
run() { docker run --rm --entrypoint "" "$IMAGE" "$@"; }

uid="$(run id -u 2>&1 || true)"
[ "$uid" = "10001" ]; check "default uid is 10001" $? "got '$uid'"

wd="$(run pwd 2>&1 || true)"
[ "$wd" = "/app" ]; check "workdir is /app" $? "got '$wd'"

out="$(run sh -c 'touch /app/.w && rm /app/.w && echo ok' 2>&1 || true)"
[ "$out" = "ok" ]; check "/app writable by default user" $? "got '$out'"

case "$IMAGE" in
  *python*)
    out="$(run uv --version 2>&1)"; rc=$?
    check "uv --version succeeds ($out)" $rc "$out"
    out="$(run python --version 2>&1)"; rc=$?
    check "python --version succeeds ($out)" $rc "$out"
    size="$(docker image inspect "$IMAGE" --format '{{.Size}}')"
    [ "$size" -lt "$MAX_PYTHON_BYTES" ]
    check "size under 250 MB ($((size / 1000000)) MB)" $? "$size bytes"
    ;;
  *node*)
    out="$(run node --version 2>&1)"; rc=$?
    check "node --version succeeds ($out)" $rc "$out"
    case "$out" in v26.*) rc=0 ;; *) rc=1 ;; esac
    check "node is v26 (Active LTS)" $rc "$out"
    ;;
  *)
    check "image name identifies runtime" 1 "expected *python* or *node* in '$IMAGE'"
    ;;
esac

exit $fail
