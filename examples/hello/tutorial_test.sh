#!/usr/bin/env bash
# The five-minute path, run exactly as the docs print it.
#
# The commands between the `>>> quickstart` and `<<< quickstart` markers are the
# single source of the tutorial page and of the landing page's proof block:
# tools/gen_quickstart.py extracts them and `--check` fails if the published
# page and this script disagree. So the tutorial cannot drift from a script CI
# runs, which is the whole reason the commands live here and not in prose.
#
# They are not merely listed here, they are what this script executes: the loop
# below runs each line. One documented divergence -- the server line is started
# in the background, because a reader runs it in a second terminal and this
# script has only one. tools/tests/test_gen_quickstart.py pins that the runner
# handles exactly one line specially.
#
# Needs Docker (the telemetry fragment) and a Go toolchain (the CLI).
set -euo pipefail

cd "$(dirname "$0")"

APP_PORT=54080
TRACE_DEADLINE=90
server_pid=""

cleanup() {
  [ -n "$server_pid" ] && kill "$server_pid" 2>/dev/null || true
  heph dev down >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# `go install` puts the CLI in GOBIN, or GOPATH/bin when GOBIN is unset.
export PATH="${GOBIN:-$(go env GOPATH)/bin}:$PATH"

QUICKSTART=$(
  cat <<'CMDS'
# >>> quickstart
go install github.com/Neoforge-Labs/hephaestus/go/cmd/heph@latest
uv add "hephkit[fastapi,observability,settings]"
heph dev up
uv run fastapi dev app.py --port 54080
curl -s "http://localhost:54080/price?amount=10.2&currency=KES"
# <<< quickstart
CMDS
)

say() { printf '\n== %s\n' "$1"; }

wait_for_server() {
  for _ in $(seq 1 60); do
    curl -fsS "http://localhost:${APP_PORT}/price?amount=1.00&currency=KES" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "FAIL: the app never answered on port ${APP_PORT}" >&2
  sed -n '1,40p' /tmp/hello-server.log >&2 || true
  return 1
}

say "running the published commands"
while IFS= read -r cmd; do
  case "$cmd" in
    '' | '#'*) continue ;;
    *'fastapi dev'*)
      # The one divergence: backgrounded, then waited for.
      echo "+ $cmd  (backgrounded; a reader runs this in a second terminal)"
      eval "$cmd" >/tmp/hello-server.log 2>&1 &
      server_pid=$!
      wait_for_server
      ;;
    *)
      echo "+ $cmd"
      eval "$cmd"
      ;;
  esac
done <<<"$QUICKSTART"

say "GET /price returns minor units"
price=$(curl -fsS "http://localhost:${APP_PORT}/price?amount=10.2&currency=KES")
echo "$price"
case "$price" in
  *'"amount":"1020"'*) ;;
  *) echo "FAIL: /price did not return 1020 minor units: $price" >&2; exit 1 ;;
esac

say "a grouped amount is a registry error, not a stack trace"
problem=$(curl -sS "http://localhost:${APP_PORT}/price?amount=1,000&currency=KES")
echo "$problem"
case "$problem" in
  *'HEPH-MONEY-422'*) ;;
  *) echo "FAIL: a grouped amount did not produce HEPH-MONEY-422: $problem" >&2; exit 1 ;;
esac

say "GET /split adds back up"
split=$(curl -fsS "http://localhost:${APP_PORT}/split?amount=1.00&currency=KES&ways=3")
echo "$split"
case "$split" in
  *'"34"'*'"33"'*'"33"'*) ;;
  *) echo "FAIL: /split did not allocate 34/33/33: $split" >&2; exit 1 ;;
esac

# The claim the tutorial actually makes: that request is already a trace, with
# no tracing code in app.py. Read it back out of Tempo instead of telling the
# reader to go and look.
say "the trace, read back from Tempo through Grafana"
trace_id=""
for _ in $(seq 1 "$TRACE_DEADLINE"); do
  found=$(curl -fsS "http://localhost:54300/api/datasources/proxy/uid/tempo/api/search?tags=service.name%3Dhello" 2>/dev/null || true)
  case "$found" in
    *'"traceID"'*)
      trace_id=$(printf '%s' "$found" | sed -n 's/.*"traceID":"\([0-9a-f]*\)".*/\1/p' | head -1)
      ;;
  esac
  [ -n "$trace_id" ] && break
  sleep 1
done

if [ -z "$trace_id" ]; then
  echo "FAIL: no trace for service.name=hello within ${TRACE_DEADLINE}s" >&2
  exit 1
fi
echo "trace id: $trace_id"
echo "open it: http://localhost:54300/explore"

say "five-minute path: PASS"
