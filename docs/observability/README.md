# Observability (Q19) — metrics, correlation IDs, structured logs

This document explains the Q19 observability surface: what `/metrics` exposes,
how a single request is traced end to end across the two services, and how to
wire Grafana.

> Decision (docs/DECISIONS.md Q19): **全套四層** — a four-layer dashboard:
> 系統 (system) · 品質 (quality) · 業務 (business) · 成本 (cost).
> The stub it replaces was "Prometheus 指標 stub + JSON log".

---

## 1. `/metrics` — Prometheus exposition

Both services expose a real Prometheus text exposition (format **v0.0.4**,
`Content-Type: text/plain; version=0.0.4; charset=utf-8`):

| Service    | URL                          |
|------------|------------------------------|
| Gateway    | `http://gateway:8010/metrics`   |
| AI Engine  | `http://ai_engine:8011/metrics` |

Implementation: `backend/shared/metrics.py` is a **dependency-free** in-process
registry (Counter / Histogram / Gauge) that renders the exposition by hand, so
the POC needs no extra `pip install`. An operator who already runs the official
client can set `METRICS_USE_PROMETHEUS_CLIENT=1` to opt in (lazy import); the
default is the hand-rolled path the test-suite exercises.

> **Security (Q30):** `/metrics` carries tenant IDs and month-to-date spend, so
> it is **gated at the app layer** on both services. Set `METRICS_TOKEN` and
> scrape with `Authorization: Bearer <METRICS_TOKEN>` (Prometheus
> `authorization: {type: Bearer, credentials_file: ...}` — see
> `ops/grafana/prometheus_scrape.example.yml`). With `METRICS_TOKEN` unset the
> endpoint answers **loopback clients only** (401 otherwise). Keep network-layer
> restriction as defence in depth.

### Metrics by layer

**系統 (system)**

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `http_request_duration_seconds` | histogram | `endpoint`, `method`, `status` | request latency → p50/p95/p99 per route (both services). Buckets 0.05 s → 450 s with the SLO thresholds (25 / 30 / 90 s) as edges; `/v1/health`, `/livez`, `/readyz` and `/metrics` are not timed. (Until 2026-10-03 the top bucket was 10 s, so every analysis fell in +Inf — FAILURE_LOG B-17.) |
| `analyze_stage_duration_seconds` | histogram | `stage`, `backend`, `outcome` | where an analysis spends its time (gateway side): one sample per AI-Engine call — `stage` = `parse` / `retrieve` / `draft` / `verify` / `deadline` / `claim_tree` / `element_comparison` — plus the gateway's own `redact` / `unmask`; `backend` = `LLM_MODE`; `outcome` = `ok` / `error` / `timeout` (the call or the AI Engine ran out of the analysis deadline — a call never started because no time was left is recorded at ~0 s) / `cancelled` (the analysis failed elsewhere and stopped this call; not this step's error). Stages overlap (dependency-graph scheduling), so this answers "which step is slow"; the total is `http_request_duration_seconds`. The same numbers come back per request in the `Server-Timing` header (§1b). |
| `audit_write_duration_seconds` | histogram | — | audit-row write latency. **SLO: p99 < 0.1s** (invariant #4). |
| `llm_errors_total` | counter | `model` | LLM call errors per model. |
| `cache_requests_total` | counter | `result` (`hit`/`miss`) | Q9 response-cache lookups on the analyze path → cache hit ratio. |
| `analyze_coalesced_total` | counter | — | analyze requests answered by joining an identical analysis already running (single-flight: a refresh / double submit). Counted on top of the cache miss before the join. |
| `dependency_up` | gauge | `dependency` | last `/readyz` evaluation per dependency, 1 = usable / 0 = failing (gateway: `audit_db`, `mapping_store`, `ai_engine`, `redis` when used; AI Engine: `warmup`, `qdrant` / `ollama` when used). `/readyz` itself only says ok / not ok. **Only as fresh as the last `/readyz` call** — nothing in this repo polls it (the Docker healthchecks stay on `/v1/health`, §1c); point your probe or a blackbox exporter at `/readyz`, or the gauge is empty / stale. |
| `cost_circuit_breaker_tripped` | gauge | — | Q18 breaker state: 1 = tripped (auto-degrade), 0 = closed. Bridged read-only from `rate_limit.cost_circuit_state()` at scrape time. |
| `cost_circuit_breaker_daily_usd` | gauge | — | realised fleet-wide LLM spend today (the breaker's input). |
| `cost_circuit_breaker_threshold_usd` | gauge | — | daily USD threshold at which the breaker trips (`COST_CIRCUIT_DAILY_USD`). |

**品質 (quality)**

| Metric | Type | Meaning |
|---|---|---|
| `citations_total` | counter | citations emitted in drafts (denominator). |
| `citations_invalid_total` | counter | citations that failed grounding (numerator → hallucination rate). |
| `prompt_injection_detected_total` | counter | prompt-injection attempts detected + neutralised (Q11). |

**業務 (business)**

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `oa_analyzed_total` | counter | `tenant` | office actions analyzed (not cache hits / errors). |
| `exports_total` | counter | `tenant`, `signed_off` | export attempts, split by attorney sign-off. |
| `signoff_refused_total` | counter | — | exports refused for missing sign-off (Q16 hard gate). |

**成本 (cost)**

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `llm_cost_usd_total` | counter | `tenant`, `model` | cumulative LLM spend (USD). |
| `llm_cost_usd_month_to_date` | gauge | `tenant`, `model` | MTD spend, bridged **read-only** from rate_limit at scrape time. |
| `llm_tokens_total` | counter | `model`, `kind` (`prompt`/`completion`) | LLM token throughput. |
| `llm_route_total` | counter | `model` | which model the Q15 router picked (local↔cloud↔cheap mix). |
| `tenant_monthly_tokens_used` | gauge | `tenant` | Q18 quota numerator: month-to-date tokens per tenant (read-only bridge from rate_limit). |
| `tenant_monthly_token_cap` | gauge | `tenant` | Q18 quota denominator: configured monthly token cap per tenant. |

### 1b. Per-request stage timing — `Server-Timing`

A successful `POST /v1/oa/analyze` (200) answers with a `Server-Timing`
header (errors — 504 / 500 — do not carry it; use the stage metric), readable in the
browser's devtools (Network → Timing), e.g.
`redact;dur=4, claim_tree;dur=12, parse;dur=8210, retrieve;dur=95, draft;dur=14650, verify;dur=310, deadline;dur=22, unmask;dur=3, total;dur=23540`
(longest call per stage, ms). A cache hit says `cache;desc=hit`, a request that
joined a running analysis says `coalesced`. Stage names and durations only —
no ids, no text.

### 1c. Liveness and readiness

| Endpoint | Both services | Checks | Answer |
|---|---|---|---|
| `GET /livez` | ✅ | nothing — the event loop answers (an `async` handler: it needs no worker thread, so a pool saturated by long inference calls cannot fail it) | `{"ok": true}` |
| `GET /readyz` | ✅ | gateway: audit DB, mapping store, the AI Engine's `/readyz`, Redis (if any backend uses it). AI Engine: start-up warm-up finished, Qdrant / Ollama when the mode uses them. Checks run on the event loop's default executor, not the request threadpool | 200 `{"ok": true}` / 503 `{"ok": false}`, re-evaluated at most every 5 s |
| `GET /v1/health` | ✅ | — | unchanged (detailed; kept for the SPA's stack lights, the smoke scripts and the Docker healthchecks) |

Point liveness probes at `/livez`, never at `/readyz` — a liveness probe that
touches a dependency turns one slow dependency into a restart loop. Which
dependency failed is in the logs and in `dependency_up`, not in the
unauthenticated answer.

The Docker images' `HEALTHCHECK` stays on `/v1/health`: docker-compose starts
the gateway only once the AI Engine is healthy (and the frontend only once the
gateway is), so a `/readyz` healthcheck would keep the whole stack from
starting while Ollama is absent or the warm-up runs — today it starts and
serves labelled degraded results instead.

The AI Engine warms up in the background at start: in `LLM_MODE=local` it
first asks Ollama to load the model (`OLLAMA_KEEP_ALIVE`), then loads the
Qwen3 embedder / reranker when configured — in that order, so they only take
the GPU if the LLM left room. It reports not-ready until done; a failed step is
logged and paid on first use, never keeps it unready. A request that arrives
mid-warm-up waits for the same load (one lock per model) instead of loading a
second copy.

### Cardinality discipline

Labels are **deliberately bounded**. `user_id` and `case_id` are NEVER labels —
they are high-cardinality and would explode the series count (and leak who did
what into the metrics store). `tenant` is the only tenant-level label and only
on metrics where per-tenant breakdown is operationally necessary. `model` is a
small fixed router set, capped at 64 chars defensively.

---

## 2. Correlation / request IDs — end-to-end tracing

Every request carries an `X-Request-ID`. One request → one id → both services'
logs.

```
client ──X-Request-ID?──▶ gateway ──X-Request-ID──▶ ai_engine
                            │                          │
                       bind + log                 bind + log
                       echo on response           echo on response
```

* **Gateway** (`request_id_middleware`, outermost layer): accepts an inbound
  `X-Request-ID` (so digiRunner / a reverse proxy can supply the trace id) or
  mints a fresh `uuid4` hex. It binds the id into a `contextvars.ContextVar`,
  echoes it on **every** response (including 4xx/5xx), and propagates it on the
  gateway→ai_engine call via `observability.request_id_headers(...)`.
* **AI Engine** (`_observability_middleware`, outermost layer): reads the
  inbound `X-Request-ID` back out, binds it, and echoes it — so its JSON log
  lines carry the **same** id as the gateway's.

The id is sanitised before use (trimmed, length-capped at 128 — the
`AnalysisResponse.request_id` limit, FAILURE_LOG B-22 — control/newline chars
stripped) so a forged header can't forge log lines.

The gateway → AI Engine calls also carry `X-Time-Budget`: the SECONDS LEFT of
one deadline per analysis (`ANALYZE_DEADLINE_SEC`, default 390 s, below the
SPA's 420 s). Relative on purpose — an absolute time would depend on the two
hosts' clocks agreeing. The AI Engine turns it into a deadline on its own
clock, binds it like the request id, and caps every **model wait** — Ollama,
Dify, each Anthropic attempt and retry backoff — by the time left. Out of time,
the AI Engine answers 504: a required step (parse, deadline) then fails the
analysis with 504; an optional one (retrieval, draft, verify, claim tree,
element comparison) is marked degraded and the result is not cached.
Not capped: CPU/GPU work inside retrieval (embedding, reranking, vector
search) runs to completion once started.

### Propagation status

| Hop | Propagated? |
|---|---|
| `/v1/oa/upload` → `/v1/ai/extract_text` | ✅ `request_id_headers` |
| `orchestrator.AIEngineClient.call` (parse / retrieve / draft / verify / deadline / claim tree / elements) | ✅ `request_id_headers(_internal_headers())` |
| Response body: `AnalysisResponse.request_id` | ✅ since 2026-10-03 the **same** bound id (it used to be a separate `uuid4`, so the id an attorney quoted was in no log — FAILURE_LOG B-14). A cache hit reports the hitting request's id. |
| SPA | ✅ reads `X-Request-ID` into `ApiError.requestId`; error banners show it as 「參考編號」 |
| AI Engine → Dify | ✅ since 2026-10-04 Dify's `user` field is `req-` + a keyed hash of the request id (`llm_client.dify_user_for`, key = `INTERNAL_TOKEN`): recompute it from a request id to find the Dify run. The id itself — client-settable via `X-Request-ID` — never reaches Dify's end-user table. One Dify end-user row per analysis. |
| Audit row | ❌ no `request_id` column yet (needs a hash-chain-aware migration); follow-up OBS-4 |

Until the audit row carries the id, join an audit row to logs by tenant +
endpoint + timestamp.

---

## 3. Structured logging

`observability.configure_logging(service)` installs a JSON log formatter +
the request-id filter on the root handler (called at the top of each app's
`main.py`). Every log line is a single-line JSON object:

```json
{"ts":"2026-06-10T09:00:00+0000","level":"INFO","logger":"patentmind.gateway.egress",
 "service":"gateway","request_id":"a1b2c3...","message":"..."}
```

* `request_id` is stamped automatically — application code just calls
  `logger.info("...")`.
* `extra={...}` kwargs are folded in as top-level fields.
* `LOG_FORMAT=text` switches to a human-readable line for local dev;
  `LOG_LEVEL` (default `INFO`) gates verbosity.

---

## 4. Grafana

Two import-ready dashboards live in `docs/observability/grafana/`:

| File | Covers |
|---|---|
| `patentmind_system_overview.json` | 系統總覽 — request rate / p50-p95-p99 latency / 4xx-5xx error rate per endpoint, Q9 cache hit ratio, Q18 cost circuit breaker state + spend-vs-threshold, Q13 audit-write p99 SLO stat. |
| `patentmind_ai_quality_cost.json` | AI 品質與成本 — tokens by model + Q15 router mix, MTD + cumulative spend per tenant/model, Q14 verifier citation strip rate, Q11 injection detections, Q18 tenant quota utilisation, OAs analyzed. Has a `tenant` template variable. |

(`ops/grafana/patentmind_q19_dashboard.json` is the original combined
four-layer board and still works; the two boards above are the maintained
split.)

### Import steps

1. Make sure Prometheus scrapes both services — start from
   `ops/grafana/prometheus_scrape.example.yml` (gateway `:8010/metrics`,
   ai_engine `:8011/metrics`).
2. In Grafana: **Dashboards → New → Import → Upload JSON file** and pick one
   of the two files (or paste its contents).
3. Grafana prompts for the **`DS_PROMETHEUS`** input — select your Prometheus
   datasource. Every panel references the datasource through that variable, so
   no JSON editing is needed for any environment.
4. Click **Import**. Repeat for the second dashboard.

Provisioning note: if you deploy dashboards via Grafana provisioning instead
of the UI import, replace the `${DS_PROMETHEUS}` references with your
provisioned datasource uid (provisioning does not resolve `__inputs`).

### Compose `monitoring` profile (Q26, zero manual import)

`docker compose --profile app --profile monitoring up -d` starts Prometheus
(`127.0.0.1:9090`, config `ops/monitoring/prometheus.yml`) and Grafana
(`127.0.0.1:3000`). Prometheus scrapes `gateway:8010` and `ai_engine:8011`
with `METRICS_TOKEN` mounted as a compose secret (never in the config file).
Grafana provisions the Prometheus datasource (uid `patentmind-prom`) and all
three dashboards; the container start script rewrites `${DS_PROMETHEUS}` to
that uid, so the JSON files here stay import-ready for the manual path above.
Requires `METRICS_TOKEN` and `GRAFANA_ADMIN_PASSWORD` in `.env`. See
`ops/README.md`.

---

## 5. Sentry (optional)

`observability.init_sentry(service)` wires crash reporting when `SENTRY_DSN`
is set (no-op otherwise). PII is not sent (`send_default_pii=False`); every
event is tagged with `service`.
