# syntax=docker/dockerfile:1.7
# PatentMind gateway (:8010) — production image (Q22/Q23, on-prem single box).
# Build from the repo root:  docker compose --profile app build gateway

# ---- build: resolve runtime deps into an isolated venv ----------------------
FROM python:3.13-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUTF8=1
WORKDIR /build
COPY backend/requirements.txt .
# Runtime only: drop the test tooling and the ML stack (the gateway never
# imports sentence-transformers / torch — only ai_engine does).
RUN grep -viE '^(pytest|sentence-transformers)' requirements.txt > runtime.txt \
 && python -m venv /opt/venv \
 && /opt/venv/bin/pip install -r runtime.txt

# ---- runtime ------------------------------------------------------------------
FROM python:3.13-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY backend/ backend/
# Shipped reference/operator data. /app/data itself is a volume (audit DB,
# mapping DB, registry edits, backups); docker/seed-data.sh fills it on start.
COPY data/case_registry.json /app/data-seed/case_registry.json
COPY data/tenant_dicts/ /app/data-seed/tenant_dicts/
COPY data/calendars/ /app/data-seed/calendars/
COPY docker/seed-data.sh /usr/local/bin/seed-data
RUN chmod 0755 /usr/local/bin/seed-data \
 && mkdir -p /app/data && chown -R app:app /app/data
USER app
EXPOSE 8010
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8010/v1/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["seed-data"]
CMD ["uvicorn", "backend.gateway.main:app", "--host", "0.0.0.0", "--port", "8010"]
