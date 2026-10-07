#!/bin/bash
# Start the one-container public demo (docker/demo.Dockerfile): ai_engine and
# gateway on loopback, nginx on :7860 in front.
#
# Each service runs under a small supervisor that restarts it when it exits.
# Hugging Face Spaces do NOT restart a container whose main process exits — the
# Space just shows a runtime error until someone restarts it (FAILURE_LOG B-55)
# — so the first version, which stopped the container on the first failure,
# would have left the demo down until the daily restart. For the same reason
# nothing after start-up may end this script: under `set -e` a failed `du` in
# the watchdog did exactly that (B-56).
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

# positive_int NAME VALUE DEFAULT: VALUE if it is a positive integer, else
# DEFAULT with a warning — a typo must not silently disable the watchdog or
# turn its sleep into a busy loop.
positive_int() {
  case $2 in
    '' | *[!0-9]*) ;;
    *) if [ "$2" -gt 0 ] 2>/dev/null; then echo "$2"; return; fi ;;
  esac
  echo "start-demo: $1=$2 is not a positive integer; using $3" >&2
  echo "$3"
}

DATA=/app/data
PAUSE=/tmp/start-demo.pause
MAX_MB=$(positive_int DEMO_DATA_MAX_MB "${DEMO_DATA_MAX_MB:-2048}" 2048)
WATCH_S=$(positive_int DEMO_WATCHDOG_SECONDS "${DEMO_WATCHDOG_SECONDS:-60}" 60)

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
# A service that dies within 10 s of starting (a configuration error, say) is
# retried with a doubling delay, up to a minute, instead of every 2 s.
supervise() {
  local name=$1 delay=2 started pid status
  shift
  while true; do
    while [ -e "$PAUSE" ]; do sleep 1; done
    started=$SECONDS
    "$@" &
    pid=$!
    echo "$pid" > "/tmp/start-demo.$name.pid"
    status=0
    wait "$pid" || status=$?
    if [ $((SECONDS - started)) -lt 10 ]; then
      delay=$((delay * 2 > 60 ? 60 : delay * 2))
    else
      delay=2
    fi
    echo "start-demo: $name exited (status $status); restarting in ${delay}s" >&2
    sleep "$delay"
  done
}

# wait_gone PID TICKS: wait up to TICKS x 0.5 s for PID to exit.
wait_gone() {
  local _
  for _ in $(seq 1 "$2"); do
    kill -0 "$1" 2>/dev/null || return 0
    sleep 0.5
  done
  return 1
}

# stop_service NAME: TERM, wait up to 20 s, then KILL and wait again — the data
# is reset only once the service is gone. The pid file is read again after each
# stop: a supervisor that passed its pause check just before the pause file
# appeared may have started the service once more.
stop_service() {
  local pid _
  for _ in 1 2 3; do
    pid=$(cat "/tmp/start-demo.$1.pid" 2>/dev/null || true)
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    kill "$pid" 2>/dev/null || true
    if ! wait_gone "$pid" 40; then
      kill -9 "$pid" 2>/dev/null || true
      wait_gone "$pid" 10 || echo "start-demo: $1 (pid $pid) did not exit after KILL" >&2
    fi
  done
}

# A pause file left by a container that was killed mid-reset (and is now
# started again — compose reuses the container, /tmp included) would hold
# every supervisor forever.
rm -f "$PAUSE"
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

# Pause the supervisors first, so the services are stopped by us (and reaped
# by their supervisors) rather than restarted or orphaned.
cleanup() {
  touch "$PAUSE"
  for name in gateway ai_engine nginx; do stop_service "$name" || true; done
  kill $(jobs -p) 2>/dev/null || true
  rm -f "$PAUSE"
}
trap cleanup EXIT
# PID 1 gets no default signal handling: stop promptly on `docker stop`.
trap 'exit 143' TERM
trap 'exit 130' INT

# Nothing in this loop may fail the script (see the top): a failed or partial
# measurement counts as 0 MB, and a failed reset is logged and the services
# start again.
while true; do
  sleep "$WATCH_S" &
  wait $! || true
  used=$(du -sm "$DATA" 2>/dev/null | cut -f1 || true)
  case $used in '' | *[!0-9]*) used=0 ;; esac
  if [ "$used" -gt "$MAX_MB" ]; then
    echo "start-demo: $DATA is ${used} MB (> ${MAX_MB} MB); resetting the demo state" >&2
    touch "$PAUSE" || true
    sleep 1 # a supervisor past its pause check records its new pid by now
    stop_service gateway || true
    stop_service ai_engine || true
    if reset_data; then
      echo "start-demo: demo state reset; restarting the services" >&2
    else
      echo "start-demo: resetting $DATA failed; restarting the services anyway" >&2
    fi
    rm -f "$PAUSE" || true
  fi
done
