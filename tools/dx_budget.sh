#!/usr/bin/env bash
# Measure the two numbers the five-minute promise rests on.
#
#   bash tools/dx_budget.sh            report both, exit 0 whatever they are
#   bash tools/dx_budget.sh --enforce  exit 1 if either is over budget
#
# The budget lives in tools/dx_budget.json and nowhere else: this script reads
# it, and so does the landing page. Change the number there and both follow.
#
# --enforce is for the scheduled run, not for every pull request: boot time on a
# shared runner is noisy enough that asserting 60 seconds per PR would make a
# real gate look flaky and get muted. CI passes --enforce on a schedule.
set -euo pipefail

cd "$(dirname "$0")/.."

BUDGET="tools/dx_budget.json"
# `go install` puts the CLI in GOBIN, or GOPATH/bin when GOBIN is unset, and
# neither is on PATH by default on a fresh runner.
command -v go >/dev/null 2>&1 && export PATH="${GOBIN:-$(go env GOPATH)/bin}:$PATH"
enforce=0
[ "${1:-}" = "--enforce" ] && enforce=1

read_budget() {
  python3 -c "import json,sys; print(json.load(open('$BUDGET'))['$1'])"
}

boot_budget=$(read_budget boot_seconds)
wheel_budget=$(read_budget wheel_mb)
wheel_target=$(read_budget wheel_target)
breached=0

# --- the wheel a user downloads ------------------------------------------
# Measured on the published artifact, not on a local build: the promise is
# about what `uv add hephkit` pulls, and a local wheel can differ.
say_wheel() {
  python3 - "$wheel_target" <<'PY'
import json, sys, urllib.request

target = sys.argv[1]
with urllib.request.urlopen("https://pypi.org/pypi/hephkit/json", timeout=30) as r:
    data = json.load(r)
version = data["info"]["version"]
# "manylinux x86_64" -> a wheel whose filename carries both tokens.
tokens = target.split()
best = None
for f in data["releases"][version]:
    name = f["filename"]
    if name.endswith(".whl") and all(t in name for t in tokens):
        if best is None or f["size"] > best["size"]:
            best = f
if best is None:
    print(f"NONE {version} no wheel matching {target!r}")
else:
    print(f"OK {version} {best['size']} {best['filename']}")
PY
}

wheel_line=$(say_wheel || echo "ERR")
case "$wheel_line" in
  OK*)
    read -r _ wheel_version wheel_bytes wheel_name <<<"$wheel_line"
    wheel_mb=$(python3 -c "print(f'{$wheel_bytes/1048576:.2f}')")
    over=$(python3 -c "print(1 if $wheel_bytes/1048576 > $wheel_budget else 0)")
    if [ "$over" = "1" ]; then
      printf 'wheel      %s MB  OVER BUDGET (%s MB)  %s\n' "$wheel_mb" "$wheel_budget" "$wheel_name"
      breached=1
    else
      printf 'wheel      %s MB  within %s MB  %s\n' "$wheel_mb" "$wheel_budget" "$wheel_name"
    fi
    ;;
  *)
    printf 'wheel      NOT MEASURED (%s)\n' "$wheel_line"
    [ "$enforce" = "1" ] && breached=1
    ;;
esac

# --- time to a running local stack ---------------------------------------
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  printf 'boot       NOT MEASURED (docker is not available)\n'
  [ "$enforce" = "1" ] && breached=1
else
  cleanup_stack() { (cd examples/hello && heph dev down >/dev/null 2>&1) || true; }
  trap cleanup_stack EXIT
  cleanup_stack
  start=$(date +%s)
  if (cd examples/hello && heph dev up >/tmp/dx-boot.log 2>&1); then
    elapsed=$(( $(date +%s) - start ))
    if [ "$elapsed" -gt "$boot_budget" ]; then
      printf 'boot       %ss  OVER BUDGET (%ss)\n' "$elapsed" "$boot_budget"
      breached=1
    else
      printf 'boot       %ss  within %ss\n' "$elapsed" "$boot_budget"
    fi
  else
    printf 'boot       FAILED (see /tmp/dx-boot.log)\n'
    breached=1
  fi
  cleanup_stack
  trap - EXIT
fi

if [ "$enforce" = "1" ] && [ "$breached" = "1" ]; then
  echo "DX budget breached." >&2
  exit 1
fi
exit 0
