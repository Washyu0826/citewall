# syntax=docker/dockerfile:1
#
# Public demo — the SPA (nginx), gateway and ai_engine in ONE container, in
# LLM_MODE=mock: synthetic data, no model calls, nothing kept across restarts.
#
#   Hugging Face Spaces (single container, port 7860): this image.
#   One command on a laptop:  docker compose -f docker-compose.demo.yml up --build
#
# NOT the production shape. A real deployment runs the services as separate
# containers (`docker compose --profile app up`, docs/DELIVERY_RUNBOOK.md),
# with real secrets, a real LLM and persistent volumes.

# ---- SPA ----------------------------------------------------------------------
FROM node:24-alpine AS spa
RUN apk add --no-cache gettext
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ .
# One-click logins send the PUBLISHED demo-{user} passwords — honoured by the
# gateway only in mock mode. No secret is inlined (client.js).
ENV VITE_DEMO_LOGIN_SECRET="" \
    VITE_DEMO_PUBLIC_PASSWORDS=true
RUN npm run build \
 && CSP_FRAME_ANCESTORS="https://huggingface.co" \
      node docker/gen-csp.mjs dist/index.html > /tmp/security-headers.conf
# The same server block as the frontend image, pointed at the gateway on
# loopback and listening on the port Hugging Face expects. Fail the build if
# the template changes shape and the substitution silently misses.
RUN GATEWAY_UPSTREAM=http://127.0.0.1:8010 envsubst '${GATEWAY_UPSTREAM}' \
      < docker/default.conf.template \
      | sed 's/listen 8080;/listen 7860;/' \
      | sed 's#server_tokens off;#server_tokens off; include /etc/nginx/demo/public.conf;#' \
      > /tmp/server.conf \
 && grep -q 'listen 7860;' /tmp/server.conf \
 && grep -q 'include /etc/nginx/demo/public.conf;' /tmp/server.conf \
 && grep -q 'proxy_pass http://127.0.0.1:8010/;' /tmp/server.conf

# ---- Python runtime deps (no ML: mock mode) -----------------------------------
FROM python:3.13-slim AS py
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUTF8=1
WORKDIR /build
COPY backend/requirements.txt .
RUN grep -viE '^(pytest|sentence-transformers)' requirements.txt > runtime.txt \
 && python -m venv /opt/venv \
 && /opt/venv/bin/pip install -r runtime.txt

# ---- runtime ------------------------------------------------------------------
FROM python:3.13-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx \
 && rm -rf /var/lib/apt/lists/*
# Hugging Face Spaces runs the container as uid 1000.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin demo
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LLM_MODE=mock \
    VECTOR_BACKEND=memory \
    EMBEDDING_BACKEND=mock \
    CACHE_BACKEND=memory \
    RATE_LIMIT_BACKEND=memory \
    REVOCATION_BACKEND=memory \
    AUDIT_BACKEND=sqlite \
    ARCHIVE_BACKEND=local \
    OCR_BACKEND=mock \
    AI_ENGINE_URL=http://127.0.0.1:8011 \
    TRUSTED_UPSTREAM_IPS="" \
    LOGIN_RPM=30 \
    OIDC_ENABLED=false \
    SAML_ENABLED=false
WORKDIR /app
COPY --from=py /opt/venv /opt/venv
COPY backend/ backend/
COPY data/case_registry.json /app/data-seed/case_registry.json
COPY data/tenant_dicts/ /app/data-seed/tenant_dicts/
COPY data/calendars/ /app/data-seed/calendars/
COPY docker/seed-data.sh /usr/local/bin/seed-data
COPY docker/demo/nginx.conf /etc/nginx/demo/nginx.conf
COPY docker/demo/public.conf /etc/nginx/demo/public.conf
COPY docker/demo/start.sh /usr/local/bin/start-demo
COPY --from=spa /src/dist /usr/share/nginx/html
COPY --from=spa /tmp/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=spa /tmp/server.conf /etc/nginx/demo/server.conf
RUN chmod 0755 /usr/local/bin/seed-data /usr/local/bin/start-demo \
 && mkdir -p /app/data && chown -R demo:demo /app/data
USER demo
EXPOSE 7860
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/api/v1/health', timeout=4).status == 200 else 1)"
CMD ["start-demo"]
