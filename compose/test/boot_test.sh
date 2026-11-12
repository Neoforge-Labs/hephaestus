#!/usr/bin/env bash
# Boot test for the compose fragments. Needs docker, aws, curl and uv (the
# MLflow provenance-class check runs the hephkit-lab distribution).
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
# The repository root: the MLflow provenance-class check below runs the lab
# distribution out of it and resolves HEAD there.
ROOT="$(cd "$DIR/.." && pwd)"
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

# The design's phase-3 claim that runs "appear in MLflow with their provenance
# class" (section 11 of the lab research-core design) is asserted HERE and
# nowhere else. Its two halves live in different places -- `lab.track` writes
# the tags, the fragment stores them -- so nothing in the Python suite could
# check it: `tests/test_track.py` drives a recording stub, which proves the
# calls are made and cannot prove they arrive. The in-repo replay gate is the
# other candidate and deliberately refuses the job: it must stay Docker-free so
# it runs on every pull request.
#
# The read-back through the REST API is the point, not a convenience.
# `lab.track` swallows every tracking failure by design -- a dropped tag is a
# warning, not an exception -- so a `tracked_run` that returned without raising
# is no evidence the tags were stored. Only asking MLflow what it holds is.
#
# Needs uv, which the boot workflow already installs. The tag names come from
# the `TAG_*` constants `lab.track` exports, so a rename moves this assertion
# with it instead of leaving a string behind.
#
# `--with` rather than `--extra track`, which is what the client belongs to:
# `--extra` writes mlflow into `python/hephkit-lab/.venv` and leaves it there --
# `uv run` does not remove an extra it was not asked for, only `uv sync --exact`
# does -- and that is the environment `hephkit-lab:test-fast` runs in, where
# `tests/test_track.py` drives a stub and asserts on what an import of mlflow
# pulls in. That assertion is a membership check, so the lab suite now stays
# green with the extra installed -- it used to assert equality and went red,
# which is how this coupling was found -- but `--with` is still what belongs
# here: it layers an ephemeral environment and leaves the project one alone,
# rather than leaving mlflow in a venv the fast lab suite then runs in. The
# floor below is a loose guard only; the `track` extra in
# `python/hephkit-lab/pyproject.toml` is the authoritative one.
mlflow_provenance_class() {
  local out rc _ recorded tagged recorded_id tagged_id
  # A legible failure rather than a confusing one from uv. This never fires in
  # this repository; it fires for a consumer that took this script without the
  # distribution it exercises, and it FAILS rather than skips, because a check
  # that skips when its subject is absent is the one way a gate passes silently.
  if [ ! -f "$ROOT/python/hephkit-lab/pyproject.toml" ]; then
    echo "      no hephkit-lab distribution at $ROOT/python/hephkit-lab, so the" \
      "provenance-class claim cannot be checked"
    return 1
  fi
  # The two MLFLOW_HTTP_REQUEST_* bounds are not tuning. The client defaults to
  # seven retries with exponential backoff and a 120 s timeout, and `lab.track`
  # swallows the eventual failure, so an unreachable server turns this check
  # into a job that hangs until the workflow timeout instead of a check that
  # fails. Measured: it ran past three minutes with the defaults.
  out="$(HEPH_BOOT_REPO="$ROOT" MLFLOW_TRACKING_URI=http://localhost:54500 \
    MLFLOW_DISABLE_AGENT_HINT=1 \
    MLFLOW_HTTP_REQUEST_MAX_RETRIES=1 MLFLOW_HTTP_REQUEST_TIMEOUT=20 \
    uv run --project "$ROOT/python/hephkit-lab" --with 'mlflow>=3' python - <<'PY' 2>&1
import json
import os
import sys
import urllib.request
from pathlib import Path

from hephkit.hashing import content_hash
from hephkit.lab.repro import capture
from hephkit.lab.track import TAG_RUN_CLASS, TAG_RUN_ID, is_enabled, tracked_run, tracking_uri

# Tracking off would make `tracked_run` a no-op that raises nothing, so this
# check would pass by tracking nothing. Refuse instead.
if not is_enabled():
    sys.exit("MLFLOW_TRACKING_URI is not set: lab.track would no-op and this check would prove nothing")

provenance = capture(
    run_id="boot-test-provenance-class",
    config_hash=content_hash({"check": "mlflow-provenance-class"}),
    data_hash=content_hash({"data": "none: this run computes one number"}),
    repo=Path(os.environ["HEPH_BOOT_REPO"]),
    lockfile=Path(os.environ["HEPH_BOOT_REPO"]) / "python" / "hephkit-lab" / "uv.lock",
)
with tracked_run("boot-test-provenance-class", provenance=provenance) as run:
    run.log_metrics({"boot": 1.0})
    run_id = run.run_id
if run_id is None:
    sys.exit(f"lab.track started no run against {tracking_uri()!r}")

# Ask MLflow what it actually holds. urllib rather than the mlflow client, so
# the read does not go through the same layer that did the write.
request = urllib.request.Request(f"{tracking_uri()}/api/2.0/mlflow/runs/get?run_id={run_id}")
with urllib.request.urlopen(request, timeout=20) as response:
    stored = json.load(response)
tags = {tag["key"]: tag["value"] for tag in stored["run"]["data"]["tags"]}
print(f"mlflow run {run_id} tags: {sorted(tags)}", file=sys.stderr)
# Marked rather than merely last: the mlflow client writes to both streams, and
# a positional read would start comparing whatever it printed most recently.
# NOTE for anyone editing this block: it is a heredoc inside a command
# substitution, and bash 3.2 scans the body for the closing paren, so a lone
# apostrophe anywhere in here is a syntax error in the whole script. Write
# "the client does" rather than "the client's".
print(
    "RESULT",
    provenance.run_class,
    tags.get(TAG_RUN_CLASS, "<absent>"),
    provenance.run_id,
    tags.get(TAG_RUN_ID, "<absent>"),
)
PY
  )"
  rc=$?
  printf '%s\n' "$out" | sed 's/^/      /'
  [ $rc -eq 0 ] || return 1
  read -r _ recorded tagged recorded_id tagged_id \
    <<<"$(printf '%s\n' "$out" | grep '^RESULT ' | tail -1)"
  [ -n "$recorded" ] && [ "$recorded" = "$tagged" ] && [ "$recorded_id" = "$tagged_id" ]
}
check "mlflow: a tracked run appears carrying its provenance class and run id" \
  mlflow_provenance_class

if [ "${FORCE_FAIL:-}" = 1 ]; then check "forced failure (self-test of cleanup)" false; fi

echo
if [ "$fails" -eq 0 ]; then echo "boot_test: PASS"; else echo "boot_test: FAIL ($fails)"; exit 1; fi
