#!/usr/bin/env bash
# Boot test for the compose fragments. Needs docker, psql, aws, curl.
#  1. each fragment alone: up --wait (120 s), then down -v
#  2. every fragment except stripe together, with per-service assertions
# The merged stack gets a larger budget than a single fragment because it is
# strictly more work: five services starting at once, where `objects` alone
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
for f in postgres objects telemetry mail redis stripe; do ALL_ARGS+=(-f "$DIR/$f.yaml"); done
trap cleanup EXIT

check() { # check <description> <command...>
  local d="$1"; shift
  if "$@"; then echo "PASS  $d"; else echo "FAIL  $d"; fails=$((fails + 1)); fi
}

# --- 1. each fragment alone ---------------------------------------------------
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

# --- 2. everything except stripe, merged --------------------------------------
MERGED=()
for f in postgres objects telemetry mail redis; do MERGED+=(-f "$DIR/$f.yaml"); done
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

check "postgres: select 1 on 54320" \
  env PGPASSWORD=heph psql -h localhost -p 54320 -U heph -d heph -tAc 'select 1'

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

if [ "${FORCE_FAIL:-}" = 1 ]; then check "forced failure (self-test of cleanup)" false; fi

echo
if [ "$fails" -eq 0 ]; then echo "boot_test: PASS"; else echo "boot_test: FAIL ($fails)"; exit 1; fi
