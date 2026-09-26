# Dify CE setup for PatentMind (Phase 3 — LLM_MODE=dify)

> Status 2026-06-11: **fully deployed and automated.** Everything below the
> "Manual fallback" section was executed end-to-end by `scripts/setup_dify.py`.
> This document records the topology, the one-command bootstrap, and the manual
> fallback for each automated step.

## Topology

```
ai_engine (:8011, LLM_MODE=dify)
   └─ POST {DIFY_API_URL}/v1/workflows/run   (Service API, Bearer DIFY_API_KEY_ANALYZE)
        Dify CE  — <PATENTMIND_INFRA_DIR>\dify  (tag 1.17.1, docker compose, nginx :8088)
           └─ workflow app "patentmind-analyze-oa"
                Start(intent: select, query: paragraph)
                  → IF intent == parse_oa
                      → LLM parse_oa        (system prompt = prompts/parse_oa.yaml)
                      → End {text}
                  → ELSE
                      → LLM draft_response  (system prompt = prompts/draft_response.yaml)
                      → End {text}
                LLM nodes: qwen2.5:7b @ Ollama (http://host.docker.internal:11434)
```

**Deliberate design choices**

- `verify_citations` does **NOT** go through Dify. The Q14 hard wall is the
  deterministic regex stage in `oa_analyzer.verify_citations`, and the LLM
  "second opinion" stays on the local deterministic verifier
  (`DifyLLM.WORKFLOW_INTENTS` in `backend/ai_engine/llm_client.py`). Sending
  it to the same qwen2.5:7b that drafted would be the model grading its own
  homework and add 30-60s latency for zero safety gain.
- Confidential cases (invariant #7) are safe on this path: Dify's LLM nodes
  run on **local Ollama** — no cloud egress exists.
- Redaction still happens in the gateway before any text reaches the AI
  engine (invariant #3) — nothing changed on that path.
- Any Dify failure degrades loudly to MockLLM with model label
  `dify/qwen2.5:7b-DEGRADED-mock` in response metadata / audit rows.

## Upgrading Dify 1.14.2 → 1.17.1 (2026-09)

1.16.1 carries security hardening (Jinja2 sandbox, API tokens) and 1.17.x adds
Human Input inside loops / Dify Agent (beta). Upgrade path for the external
deployment in `<PATENTMIND_INFRA_DIR>\dify`:

1. **Back up** the Dify Postgres (`docker compose exec db pg_dump ...`) and the
   `volumes/` directory.
2. `git fetch --tags && git checkout 1.17.1` in the Dify clone, then re-diff
   `docker/.env` against the new `docker/.env.example`.
3. **Breaking env rename:** `EDITION` → `DEPLOYMENT_EDITION` (1.17.0). Rename
   the key in `docker/.env` (value stays `SELF_HOSTED`).
4. **Bundled Weaviate 1.27 → 1.39 (1.17.1):** skipping minors is unsupported
   and can silently break vector search. PatentMind does **not** use Dify
   knowledge bases (RAG lives in our own Qdrant), so the simplest safe path is
   to stop the stack and delete `volumes/weaviate` before starting 1.17.1. If
   you did create knowledge bases, follow the staged Weaviate upgrade in the
   1.17.1 release notes instead.
5. `docker compose pull && docker compose up -d`, then
   `docker compose exec api flask db upgrade` (1.17.1 folds the legacy
   model-type migration into `db upgrade`; no separate `data-migrate` step).
6. Re-run `python scripts/setup_dify.py` (idempotent) and
   `bash scripts/smoke_dify.sh`; check the Ollama plugin still loads
   `qwen2.5:7b`.

The Phase-3 full-DAG template `dify_workflows/analyze_oa.workflow.json` now
declares `dify_version_required >= 1.17.0` and routes every LLM node through
local Ollama when `security_level != public` (guarded by
`tests/unit/test_dify_workflow_routing.py`). It is **not** what
`setup_dify.py` deploys — that script builds and imports its own minimal
all-Ollama DSL.

## Start / stop the Dify stack

```bash
cd /d/patentmind-infra/dify/docker
docker compose up -d        # start  (≈60s to healthy on this machine)
docker compose stop         # stop, keep state
docker compose down         # stop + remove containers (volumes/state survive)
```

Ports: nginx `:8088` (console UI + Service API). Dify's internal postgres /
redis / weaviate are **not** bound to the host (no conflict with
patentmind-redis :6379, patentmind-qdrant :6333, pulse-db :5433).

Console: <http://localhost:8088> — credentials in `<repo>\.env`
(`DIFY_ADMIN_EMAIL` / `DIFY_ADMIN_PASSWORD`).

## One-command bootstrap (idempotent)

```bash
cd /d/patentmind-poc
PYTHONUTF8=1 python scripts/setup_dify.py
```

Does: admin setup → console login → Ollama plugin install → register
qwen2.5:7b (llm) + nomic-embed-text (embedding) → import workflow DSL
(generated from `backend/ai_engine/prompts/*.yaml`) → publish → mint Service
API key → write `DIFY_API_KEY_ANALYZE` into `.env`.

Then set `LLM_MODE=dify` and restart the backend. Smoke test:

```bash
bash scripts/smoke_dify.sh
```

## Prompt updates

The Dify LLM-node prompts are synced from `backend/ai_engine/prompts/*.yaml`
**at import time only**. After editing a prompt YAML, either re-import (delete
the app in the console, re-run `setup_dify.py`) or paste the new `system:`
block into the LLM node in the visual editor and re-publish. The visual editor
is the demo story for 昕力科技 — operators can iterate without a deploy.

## Host-specific gotcha: Avast TLS interception

This host runs Avast, which MITMs outbound TLS. Containers reject its
certificate (`UnknownIssuer`), which broke marketplace plugin downloads and
the plugin daemon's `uv pip install`. Fixes (all in
`<PATENTMIND_INFRA_DIR>\dify\docker\docker-compose.override.yaml` — NOT part of
upstream Dify):

1. `volumes/certs/ca-bundle.crt` = stock container CA bundle + the exported
   "Avast Web/Mail Shield Root" certificate, mounted over
   `/etc/ssl/certs/ca-certificates.crt` in `api` / `worker` / `plugin_daemon`.
2. `PIP_EXTRA_ARGS: "--native-tls"` on `plugin_daemon` — the daemon spawns
   `uv` with a *clean* environment, so `SSL_CERT_FILE`/`UV_NATIVE_TLS` env
   vars never reach it; the CLI flag does.
3. `scripts/setup_dify.py` has a host-side fallback that downloads the signed
   `.difypkg` and installs via `upload/pkg` when the api container cannot
   reach the marketplace.

On a clean enterprise host (no MITM AV) none of this is needed.

## What was automated vs manual

| Step | Automated? | How |
|---|---|---|
| Dify clone + checkout 1.17.1 (was 1.14.2 until 2026-09) | yes | git (`<PATENTMIND_INFRA_DIR>\dify`) |
| `.env` (SECRET_KEY, EXPOSE_NGINX_PORT=8088) | yes | sed during setup |
| docker compose up | yes | one command |
| Admin account | yes | `POST /console/api/setup` |
| Console login | yes | cookie + `X-CSRF-Token` (Dify ≥1.14 uses cookies, not bearer) |
| Ollama plugin install | yes | marketplace API (+ local-pkg fallback) |
| Model registration (validated against Ollama) | yes | `POST .../models/credentials` |
| Workflow app | yes | DSL YAML import (`POST /console/api/apps/imports`, DSL version 0.6.0) |
| Publish + Service API key | yes | console API |
| Backend wiring (`LLM_MODE=dify`) | yes | `backend/ai_engine/llm_client.py:DifyLLM` |

**Nothing required manual console clicks.** Manual fallback if the script
cannot be used: log into <http://localhost:8088>, install "Ollama" from the
plugin marketplace, add model `qwen2.5:7b` (type LLM, base URL
`http://host.docker.internal:11434`, mode chat), create a Workflow app named
`patentmind-analyze-oa` with the graph shown above (paste the `system:` blocks
from `backend/ai_engine/prompts/parse_oa.yaml` / `draft_response.yaml`),
publish, create an API key under "API Access", and put it in `.env` as
`DIFY_API_KEY_ANALYZE`.

## Verification artifacts

- `tests/unit/test_dify_llm.py` — 14 hermetic unit tests (request shape,
  JSON extraction, degrade paths, verifier-stays-local, router wiring).
- `scripts/smoke_dify.sh` — live smoke against the running Dify.
- `data/dify_e2e_proof.json` — full gateway `/v1/oa/analyze` response with
  `LLM_MODE=dify` on the TW sample OA (antecedent_basis on claim 9 parsed,
  zh-TW 申復書 drafted by qwen2.5:7b, verifier stripped an ungrounded ref,
  model `dify/qwen2.5:7b`, no degrade).
