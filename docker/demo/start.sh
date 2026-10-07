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

seed-data true
mkdir -p /tmp/nginx

uvicorn backend.ai_engine.main:app --host 127.0.0.1 --port 8011 &
uvicorn backend.gateway.main:app --host 127.0.0.1 --port 8010 &
# -e: before reading the config nginx opens its compiled-in error log under
# /var/log/nginx, which this unprivileged user cannot write.
nginx -e /dev/stderr -c /etc/nginx/demo/nginx.conf -g 'daemon off;' &

trap 'kill $(jobs -p) 2>/dev/null || true' EXIT
set +e
wait -n
status=$?
echo "start-demo: a process exited (status $status); stopping the container" >&2
exit "$status"
