#!/usr/bin/env bash
# Boot test for the compose fragments. Needs docker, aws, curl.
#  1. each fragment alone: up --wait (120 s), then down -v
#  2. every fragment except stripe together, with per-service assertions
# The merged stack gets a larger budget than a single fragment because it is
# strictly more work: six services starting at once, where `objects` alone
# takes ~43 s. Sharing one 120 s timeout made this marginal, and it failed on a
# runner while every fragment passed alone.
# stripe is excluded from the live run because it needs a real STRIPE_API_KEY;
# its contract (fails without a key, parses with one) is checked via `config`.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
P=heph-boot
WAIT=(--wait --wait-timeout 120)
MERGED_WAIT=(--wait --wait-timeout 300)
fails=0

dc() { docker compose -p "$P" "$@"; }
cleanup() { dc "${ALL_ARGS[@]}" down -v --remove-orphans >/dev/null 2>&1; dc down -v --remove-orphans >/dev/null 2>&1; }
ALL_ARGS=()
for f in postgres objects telemetry mail redis stripe mlflow; do ALL_ARGS+=(-f "$DIR/$f.yaml"); done
trap cleanup EXIT

check() { # check <description> <command...>
  local d="$1"; shift
  if "$@"; then echo "PASS  $d"; else echo "FAIL  $d"; fails=$((fails + 1)); fi
}

# --- 1. each fragment alone ---------------------------------------------------
# mlflow is not here: it depends on postgres and objects, so it only exists in
# the merged stack below.
for f in postgres objects telemetry mail redis; do
  start=$SECONDS
  check "$f alone: up --wait" dc -f "$DIR/$f.yaml" up -d "${WAIT[@]}"
  echo "TIME  $f alone healthy in $((SECONDS - start))s"
  dc -f "$DIR/$f.yaml" down -v --remove-orphans >/dev/null 2>&1
done

# stripe: requires a key, and parses when one is given.
stripe_needs_key() { local out; out="$(env -u STRIPE_API_KEY docker compose -p "$P" -f "$DIR/stripe.yaml" config 2>&1)" && return 1; grep -q 'STRIPE_API_KEY is required' <<<"$out"; }
check "stripe refuses to start without STRIPE_API_KEY" stripe_needs_key
check "stripe config valid with a key" \
  env STRIPE_API_KEY=sk_test_dummy docker compose -p "$P" -f "$DIR/stripe.yaml" config -q

# mlflow: depends_on postgres and objects, so it cannot run alone; assert the
# wiring resolves when it sits beside them.
check "mlflow config valid beside postgres and objects" \
  docker compose -p "$P" -f "$DIR/postgres.yaml" -f "$DIR/objects.yaml" -f "$DIR/mlflow.yaml" config -q

# --- 2. everything except stripe, merged --------------------------------------
MERGED=()
for f in postgres objects telemetry mail redis mlflow; do MERGED+=(-f "$DIR/$f.yaml"); done
start=$SECONDS
# On failure, say WHICH service is unhealthy. `up --wait` only reports that the
# wait expired, which is why a runner failure here was previously undiagnosable.
merged_up() {
  dc "${MERGED[@]}" up -d "${MERGED_WAIT[@]}" && return 0
  echo "---- merged stack state ----" >&2
  dc "${MERGED[@]}" ps >&2 || true
  return 1
}
check "merged stack: up --wait" merged_up
echo "TIME  merged stack healthy in $((SECONDS - start))s"

# Two separate properties, neither needing a Postgres client on the host: the
# database answers (asked inside the container, which already ships psql), and
# the 54xxx host port is published (a bare TCP connect). The old single check
# used a host psql, which meant installing postgresql-client from the Ubuntu
# mirrors on every CI run — a network dependency that took the job down when
# the runner could not resolve them. redis has always been checked this way.
pg_answers() { [ "$(dc "${MERGED[@]}" exec -T postgres psql -U heph -d heph -tAc 'select 1')" = 1 ]; }
check "postgres: select 1 answers 1" pg_answers
# curl is already required here, and unlike bash's /dev/tcp it works on macOS,
# whose /bin/bash is built without net redirections. Postgres does not speak
# HTTP, so an accepted connection ends in a protocol error (52, empty reply)
# while nothing listening gives 7, "couldn't connect". Only 7 means the port
# mapping is missing, which is the property this asserts.
pg_port_published() { curl -s --connect-timeout 5 http://127.0.0.1:54320 >/dev/null 2>&1; [ $? -ne 7 ]; }
check "postgres: host port 54320 accepts a connection" pg_port_published

s3() { AWS_ACCESS_KEY_ID=heph AWS_SECRET_ACCESS_KEY=heph-dev-secret AWS_DEFAULT_REGION=us-east-1 \
  aws --endpoint-url http://localhost:54333 s3 ls 2>&1; }
s3_alive() { local out rc; out="$(s3)"; rc=$?; [ $rc -eq 0 ] || grep -q 'AccessDenied\|403' <<<"$out"; }
check "objects: aws s3 ls on 54333 (empty list or 403)" s3_alive

check "grafana: /api/health on 54300" curl -sf localhost:54300/api/health -o /dev/null
otlp_code() { curl -s -o /dev/null -w '%{http_code}' -X POST localhost:54318/v1/traces -H 'content-type: application/json' -d '{}'; }
otlp_ok() { local c; c="$(otlp_code)"; echo "      OTLP HTTP status $c"; [ "$c" = 200 ] || [ "$c" = 400 ]; }
check "otlp http: POST /v1/traces on 54318 is 200 or 400" otlp_ok
mail_ok() { [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:54825/)" = 200 ]; }
check "mailpit UI on 54825 returns 200" mail_ok
redis_ok() { [ "$(dc "${MERGED[@]}" exec -T redis redis-cli ping)" = PONG ]; }
check "redis answers PONG" redis_ok

mlflow_ok() { [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:54500/health)" = 200 ]; }
check "mlflow: /health on 54500 returns 200" mlflow_ok
# The tracking API proves the Postgres backend store is wired, not just that the
# process is up: listing experiments reads the database.
mlflow_backend_ok() { curl -sf "localhost:54500/api/2.0/mlflow/experiments/search?max_results=1" -o /dev/null; }
check "mlflow: experiments/search answers (postgres backend store)" mlflow_backend_ok

if [ "${FORCE_FAIL:-}" = 1 ]; then check "forced failure (self-test of cleanup)" false; fi

echo
if [ "$fails" -eq 0 ]; then echo "boot_test: PASS"; else echo "boot_test: FAIL ($fails)"; exit 1; fi
