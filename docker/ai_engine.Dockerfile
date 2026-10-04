# syntax=docker/dockerfile:1.7
# PatentMind ai_engine (:8011) — production image (Q22/Q23, on-prem single box).
# Build from the repo root:  docker compose --profile app build ai_engine
#
# INSTALL_ML=true (default) installs sentence-transformers on a CPU-only torch
# wheel (~1 GB instead of the multi-GB CUDA build) so EMBEDDING_BACKEND=bge-m3 /
# qwen3 and the reranker work. The local LLM itself runs in Ollama on the HOST
# (GPU) and is reached via host.docker.internal — the container needs no GPU.
# INSTALL_ML=false gives a slim image for EMBEDDING_BACKEND=mock|lexical.

ARG INSTALL_ML=true

# ---- build --------------------------------------------------------------------
FROM python:3.13-slim AS build
ARG INSTALL_ML
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUTF8=1
WORKDIR /build
COPY backend/requirements.txt .
RUN python -m venv /opt/venv \
 && if [ "$INSTALL_ML" = "true" ]; then \
      /opt/venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch \
      && grep -viE '^pytest' requirements.txt > runtime.txt ; \
    else \
      grep -viE '^(pytest|sentence-transformers)' requirements.txt > runtime.txt ; \
    fi \
 && /opt/venv/bin/pip install -r runtime.txt

# ---- runtime ------------------------------------------------------------------
FROM python:3.13-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/data/hf_cache
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY backend/ backend/
COPY data/calendars/ /app/data-seed/calendars/
COPY docker/seed-data.sh /usr/local/bin/seed-data
RUN chmod 0755 /usr/local/bin/seed-data \
 && mkdir -p /app/data && chown -R app:app /app/data
USER app
EXPOSE 8011
# Deliberately /v1/health, not /readyz: docker-compose starts the gateway only
# once this is healthy, and /readyz is not ready without Ollama or before the
# warm-up finishes — the whole stack would refuse to start instead of serving
# labelled degraded results (docs/observability §1c).
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8011/v1/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["seed-data"]
CMD ["uvicorn", "backend.ai_engine.main:app", "--host", "0.0.0.0", "--port", "8011"]
