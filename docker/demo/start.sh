#!/bin/bash
# Start the one-container public demo (docker/demo.Dockerfile): ai_engine and
# gateway on loopback, nginx on :7860 in front. If any of the three stops, stop
# the others and exit, so the platform restarts the container instead of
# serving half an app.
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

# A fresh start every time — also when compose restarts the SAME container
# (restart: unless-stopped): the audit chain is keyed by the per-start
# AUDIT_HMAC_KEY above, and one visitor's edits (case registry, audit rows)
# must not outlive the next restart.
if python -c "import os, sys; sys.exit(0 if os.path.ismount('/app/data') else 1)"; then
  echo "start-demo: /app/data is a mounted volume; not wiping it (set a fixed AUDIT_HMAC_KEY to keep its audit chain verifiable)" >&2
else
  find /app/data -mindepth 1 -delete
fi
seed-data true
mkdir -p /tmp/nginx

# --no-proxy-headers: uvicorn trusts X-Forwarded-For from 127.0.0.1 by
# default, and here nginx IS 127.0.0.1 — a visitor's own header would
# become request.client.host, defeating the per-IP login limit. The
# services see nginx; every visitor shares the login bucket.
uvicorn backend.ai_engine.main:app --host 127.0.0.1 --port 8011 --no-proxy-headers &
uvicorn backend.gateway.main:app --host 127.0.0.1 --port 8010 --no-proxy-headers &
# -e: before reading the config nginx opens its compiled-in error log under
# /var/log/nginx, which this unprivileged user cannot write.
nginx -e /dev/stderr -c /etc/nginx/demo/nginx.conf -g 'daemon off;' &

trap 'kill $(jobs -p) 2>/dev/null || true' EXIT
# PID 1 gets no default signal handling: stop promptly on `docker stop`.
trap 'exit 143' TERM
trap 'exit 130' INT
set +e
wait -n
status=$?
echo "start-demo: a process exited (status $status); stopping the container" >&2
exit "$status"
