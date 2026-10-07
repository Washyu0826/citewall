#!/bin/bash
# Start the one-container public demo (docker/demo.Dockerfile): ai_engine and
# gateway on loopback, nginx on :7860 in front.
#
# Each service runs under a small supervisor that restarts it when it exits.
# Hugging Face Spaces do NOT restart a container whose main process exits — the
# Space just shows a runtime error until someone restarts it (FAILURE_LOG B-55)
# — so the first version, which stopped the container on the first failure,
# would have left the demo down until the daily restart.
#
# A watchdog bounds the disk: every unique masked entity is stored for
# un-masking, so one visitor can add megabytes per request. Past
# DEMO_DATA_MAX_MB the services are paused, the data — nothing worth keeping
# in a mock-mode demo — is reset, and they start again.
set -euo pipefail

# Per-start secrets. Nothing is persisted (mock mode, synthetic data), so a
# restart simply signs everyone out. A value passed in the environment wins.
gen() { python -c "import secrets; print(secrets.token_hex($1))"; }
export JWT_SECRET="${JWT_SECRET:-$(gen 32)}"
export INTERNAL_TOKEN="${INTERNAL_TOKEN:-$(gen 32)}"
export MAPPING_ENCRYPTION_KEY="${MAPPING_ENCRYPTION_KEY:-$(gen 32)}"
export AUDIT_HMAC_KEY="${AUDIT_HMAC_KEY:-$(gen 32)}"
# Without a token, /metrics answers loopback callers — and in this container
# nginx forwards every visitor from loopback. A random token closes it.
export METRICS_TOKEN="${METRICS_TOKEN:-$(gen 32)}"

if [ "${LLM_MODE:-}" != "mock" ]; then
  echo "start-demo: this image is the public mock-mode demo; LLM_MODE=${LLM_MODE:-} refused" >&2
  exit 1
fi

DATA=/app/data
PAUSE=/tmp/start-demo.pause
MAX_MB="${DEMO_DATA_MAX_MB:-512}"

# A fresh start every time — also when compose restarts the SAME container
# (restart: unless-stopped): the audit chain is keyed by the per-start
# AUDIT_HMAC_KEY above, and one visitor's edits (case registry, audit rows)
# must not outlive the next restart.
reset_data() {
  if python -c "import os, sys; sys.exit(0 if os.path.ismount('$DATA') else 1)"; then
    echo "start-demo: $DATA is a mounted volume; not wiping it (set a fixed AUDIT_HMAC_KEY to keep its audit chain verifiable)" >&2
  else
    find "$DATA" -mindepth 1 -delete
  fi
  seed-data true
}

# supervise NAME COMMAND...: run it, restart it when it exits; wait while the
# watchdog holds the pause file. The service's pid goes to /tmp/start-demo.NAME.pid.
supervise() {
  local name=$1
  shift
  while true; do
    while [ -e "$PAUSE" ]; do sleep 1; done
    "$@" &
    local pid=$!
    echo "$pid" > "/tmp/start-demo.$name.pid"
    local status=0
    wait "$pid" || status=$?
    echo "start-demo: $name exited (status $status); restarting" >&2
    sleep 2
  done
}

# stop_service NAME: TERM, then wait (KILL after 20 s) — data is reset only
# once nothing has it open.
stop_service() {
  local pid
  pid=$(cat "/tmp/start-demo.$1.pid" 2>/dev/null || true)
  [ -n "$pid" ] || return 0
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 40); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.5
  done
  kill -9 "$pid" 2>/dev/null || true
}

reset_data
mkdir -p /tmp/nginx

# --no-proxy-headers: uvicorn trusts X-Forwarded-For from 127.0.0.1 by
# default, and here nginx IS 127.0.0.1 — a visitor's own header would
# become request.client.host, defeating the per-IP login limit. The
# services see nginx; every visitor shares the login bucket.
supervise ai_engine uvicorn backend.ai_engine.main:app --host 127.0.0.1 --port 8011 --no-proxy-headers &
supervise gateway uvicorn backend.gateway.main:app --host 127.0.0.1 --port 8010 --no-proxy-headers &
# -e: before reading the config nginx opens its compiled-in error log under
# /var/log/nginx, which this unprivileged user cannot write.
supervise nginx nginx -e /dev/stderr -c /etc/nginx/demo/nginx.conf -g 'daemon off;' &

cleanup() {
  kill $(jobs -p) 2>/dev/null || true
  for name in gateway ai_engine nginx; do stop_service "$name"; done
}
trap cleanup EXIT
# PID 1 gets no default signal handling: stop promptly on `docker stop`.
trap 'exit 143' TERM
trap 'exit 130' INT

while true; do
  sleep "${DEMO_WATCHDOG_SECONDS:-60}" &
  wait $! || true
  used=$(du -sm "$DATA" 2>/dev/null | cut -f1)
  if [ "${used:-0}" -gt "$MAX_MB" ]; then
    echo "start-demo: $DATA is ${used} MB (> ${MAX_MB} MB); resetting the demo state" >&2
    touch "$PAUSE"
    stop_service gateway
    stop_service ai_engine
    reset_data
    rm -f "$PAUSE"
  fi
done
