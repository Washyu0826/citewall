"""Gateway orchestrator (Q1 厚 Gateway + Follow-up C 混合 orchestration).

The Gateway owns the *business* flow:
    1. parse OA  → call AI Engine /v1/parse_oa
    2. for each rejection → call AI Engine /v1/retrieve_prior_art
    3. for each rejection → call AI Engine /v1/draft_response
    4. verify drafts → call AI Engine /v1/verify_citations
    5. compute deadline → call AI Engine /v1/deadline
    6. assemble final AnalysisResponse

The AI Engine (Dify mock) only does **single-step AI inference**.
No business state lives in Dify.  This makes business logic unit-testable
and lets us swap AI providers without touching orchestration.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import httpx
from fastapi import HTTPException

from backend.gateway import masking
from backend.gateway.auth import _internal_headers
from backend.gateway.rate_limit import cost_provenance_for, estimate_cost
from backend.shared import metrics, time_budget
from backend.shared.case_registry import security_level_for_case
from backend.shared.config import settings
from backend.shared.models import (
    AnalysisRequest,
    AnalysisResponse,
    ClaimElementTable,
    ClaimNode,
    CostMeta,
    DeadlineInfo,
    DraftResponse,
    OADocument,
    RedactionSummary,
    RetrievalHit,
    SentenceAlignment,
    User,
)
from backend.shared.observability import current_request_id, request_id_headers

logger = logging.getLogger("patentmind.gateway.egress")


class EgressGuardError(Exception):
    """Raised when the egress guard detects raw (un-redacted) PII in an
    outbound payload to the AI Engine.

    Invariant #3 (Q3 + Q10): redaction is mandatory before any LLM call.
    Hitting this means the masking layer was bypassed for some field — we
    FAIL CLOSED (block the call) rather than leak PII to the AI Engine.
    """

    def __init__(self, rule_id: str, path: str):
        self.rule_id = rule_id
        self.path = path
        super().__init__(
            f"EGRESS GUARD: unredacted PII pattern {rule_id!r} detected in "
            f"outbound payload to {path!r}"
        )


def _scan_value_for_pii(value: Any) -> str | None:
    """Recursively scan a JSON-serialisable value for raw PII patterns.

    Reuses the *already-compiled* `masking.PII_RULES` patterns (compiled once
    at import time in masking.py) — no per-call recompile / re-import.

    Returns the first matching `rule_id` (so the caller can name it in the
    alert), or None if the value is clean.

    Placeholders like ``[EMAIL_A1B2C3D4]`` are *expected* to pass: the email
    regex requires an ``@`` and the bracketed-hex placeholder shape has none,
    and the SSN/ID/phone patterns are anchored on digit runs the placeholder
    doesn't contain. We never strip placeholders before scanning — defence in
    depth means we scan the literal outbound bytes.
    """
    if isinstance(value, str):
        for rule in masking.PII_RULES:
            if (rule.search_pattern or rule.pattern).search(value):
                return rule.rule_id
        return None
    if isinstance(value, dict):
        for k, v in value.items():
            # Keys are usually field names (no PII), but scan them too —
            # cheap and closes the "PII smuggled as a dict key" hole.
            if isinstance(k, str):
                for rule in masking.PII_RULES:
                    if (rule.search_pattern or rule.pattern).search(k):
                        return rule.rule_id
            hit = _scan_value_for_pii(v)
            if hit is not None:
                return hit
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            hit = _scan_value_for_pii(item)
            if hit is not None:
                return hit
        return None
    # int / float / bool / None — no string content to leak.
    return None


def _assert_no_raw_pii(path: str, payload: dict) -> None:
    """Egress chokepoint enforcing invariant #3.

    If `EGRESS_GUARD_ENABLED` is on (default) and the outbound `payload`
    contains a raw PII pattern, log an error-level alert and raise
    `EgressGuardError` (fail closed). No-op when the guard is disabled.
    """
    if not settings.EGRESS_GUARD_ENABLED:
        return
    rule_id = _scan_value_for_pii(payload)
    if rule_id is not None:
        # Never log the offending value itself — that would re-leak the PII
        # into the log sink. Log the rule id + destination path only.
        logger.error(
            "EGRESS GUARD: unredacted PII pattern %s detected in outbound payload to %s",
            rule_id,
            path,
        )
        raise EgressGuardError(rule_id, path)


_AI_CALL_HEADROOM_SEC = 30.0

# AnalysisResponse.request_id is max_length=128 (models.py).
_MAX_RESPONSE_REQUEST_ID = 128


def _user_facing_request_id() -> str:
    """The id shown to the user: the bound X-Request-ID when it fits the
    response schema, else a fresh uuid.

    A client can supply X-Request-ID. If a longer id than the response model
    allows reached AnalysisResponse(...), validation failed AFTER every model
    call had run — a 500 whose quota reservation was refunded, i.e. free model
    spend on demand (FAILURE_LOG B-22). The sanitiser now caps at 128 too;
    this check keeps the two limits from drifting apart again.
    """
    rid = current_request_id()
    if rid and len(rid) <= _MAX_RESPONSE_REQUEST_ID:
        return rid
    return str(uuid.uuid4())


def ai_call_timeout_sec() -> float:
    """Budget for ONE gateway→AI-Engine call, per LLM backend.

    Timeouts must nest: the outer (gateway) wait has to outlast the inner
    (AI Engine → model) one, so the AI Engine's own timeout and its labelled
    degrade-to-mock path answer first and the gateway relays a structured
    result. A flat 60 s here was shorter than the 600 s Ollama budget, so in
    local mode a 60–120 s zh-TW draft was silently replaced by a placeholder
    while Ollama kept generating for nobody (FAILURE_LOG B-13).

    The SPA allows 420 s per analysis (frontend/src/api/client.js), so inner
    budgets stay at ~300 s. Since BE-4 every call is ALSO capped by the
    analysis deadline (AIEngineClient._timeout; the AI Engine gets the seconds
    left as X-Time-Budget) — this is only the per-call ceiling.
    """
    mode = settings.LLM_MODE
    if mode == "dify":
        return float(settings.DIFY_TIMEOUT_SEC) + _AI_CALL_HEADROOM_SEC
    if mode == "local":
        return float(settings.OLLAMA_TIMEOUT_SEC) + _AI_CALL_HEADROOM_SEC
    if mode == "anthropic":
        # A cited draft is two model calls back to back (llm_client draft path).
        return 2 * float(settings.LLM_REQUEST_TIMEOUT_SEC) + _AI_CALL_HEADROOM_SEC
    return 60.0


class AnalysisTimeout(HTTPException):
    """A step could not finish inside the analysis deadline (504).

    Raised for the per-call HTTP timeout and when the whole-request budget is
    already spent. Saga steps (retrieve / draft / verify / claim tree / element
    comparison) catch it and degrade that step like any other failure; the
    required steps (parse, deadline) let it surface as a 504 the SPA treats as
    a retryable timeout.
    """

    def __init__(self, detail: str):
        super().__init__(status_code=504, detail=detail)


# A call is only started with at least this much of the analysis budget left.
_MIN_CALL_BUDGET_SEC = 2.0

# AI-Engine path → stage label (analyze_stage_duration_seconds, Server-Timing).
_STAGE_FOR_PATH = {
    "/v1/parse_oa": "parse",
    "/v1/retrieve_prior_art": "retrieve",
    "/v1/draft_response": "draft",
    "/v1/verify_citations": "verify",
    "/v1/deadline": "deadline",
    "/v1/claim_tree": "claim_tree",
    "/v1/element_comparison": "element_comparison",
}


class AIEngineClient:
    """Thin client to the AI Engine for ONE analysis.

    Carries the analysis deadline (BE-4) and records how long every call
    took (OBS-3): ``timings`` holds (stage, seconds, outcome) per call.
    """

    def __init__(self, base_url: str = settings.AI_ENGINE_URL, *, deadline: float | None = None):
        self.base_url = base_url.rstrip("/")
        self.deadline = deadline  # absolute epoch seconds, or None (no budget)
        self.timings: list[tuple[str, float, str]] = []

    def record(self, stage: str, seconds: float, outcome: str = "ok") -> None:
        self.timings.append((stage, seconds, outcome))
        metrics.ANALYZE_STAGE_DURATION.observe(
            seconds, {"stage": stage, "backend": settings.LLM_MODE, "outcome": outcome}
        )

    def stage_ms(self) -> dict[str, int]:
        """Longest call per stage, in ms (stages run concurrently, so the
        slowest call is what the critical path waited for)."""
        out: dict[str, int] = {}
        for stage, seconds, _ in self.timings:
            out[stage] = max(out.get(stage, 0), int(seconds * 1000))
        return out

    def _timeout(self, path: str) -> float:
        if self.deadline is None:
            return ai_call_timeout_sec()
        left = self.deadline - time.time()
        if left < _MIN_CALL_BUDGET_SEC:
            raise AnalysisTimeout(f"analysis deadline reached before {path}")
        return max(1.0, min(ai_call_timeout_sec(), left))

    async def call(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        # ---- Egress guard (Q3 / invariant #3) ----
        # This is the SINGLE egress point to the AI Engine. Before any bytes
        # leave the gateway we scan the whole payload for raw PII that should
        # have been redacted upstream. Fail closed if redaction escaped.
        # Inline, on purpose, and kept cheap instead (~0.1 s at most; e-mail
        # existence uses its linear search pattern). A worker thread would only
        # let the event loop in between two searches (re holds the GIL for
        # each) and changed cancellation and deadline behaviour (B-56, B-57).
        _assert_no_raw_pii(path, payload)
        stage = _STAGE_FOR_PATH.get(path, path.rsplit("/", 1)[-1])
        started = time.monotonic()
        # ok | error | timeout (incl. "no time left to start", recorded at
        # ~0 s) | cancelled (the analysis failed elsewhere and stopped this
        # call — not this step's error; review W2-A7).
        outcome = "error"
        try:
            try:
                timeout = self._timeout(path)
            except AnalysisTimeout:
                outcome = "timeout"
                raise
            # The per-call wait outlives the slowest model path in every mode
            # (ai_call_timeout_sec) but never the analysis deadline.
            async with httpx.AsyncClient(timeout=timeout) as client:
                # C-2: the AI Engine refuses non-health requests without
                # X-Internal-Token (server-side only, never the SPA's).
                # request_id_headers adds the bound X-Request-ID so both
                # services' logs carry the same id; X-Time-Budget (seconds
                # left) lets the AI Engine cap its own model waits.
                headers = request_id_headers(_internal_headers())
                if self.deadline is not None:
                    headers[time_budget.BUDGET_HEADER] = time_budget.format_budget(self.deadline)
                try:
                    r = await client.post(url, json=payload, headers=headers)
                except httpx.TimeoutException as exc:
                    outcome = "timeout"
                    raise AnalysisTimeout(f"{stage} step timed out") from exc
                if r.status_code == 504:
                    # The AI Engine ran out of the budget we sent it.
                    outcome = "timeout"
                    raise AnalysisTimeout(f"{stage} step ran out of the analysis deadline")
                r.raise_for_status()
                outcome = "ok"
                return r.json()
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            self.record(stage, time.monotonic() - started, outcome)


async def _cancel_and_drain(*tasks: asyncio.Task) -> None:
    """Cancel unfinished tasks and wait for them, so nothing keeps calling the
    AI Engine after the analysis has failed (and no task error goes unseen)."""
    pending = [t for t in tasks if t is not None and not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    for t in tasks:
        if t is not None and t.done() and not t.cancelled():
            t.exception()  # finished with an error before the cancel: mark it seen


async def orchestrate_analysis(
    user: User,
    req: AnalysisRequest,
    circuit_open: bool = False,
    *,
    pre_redacted: tuple[str, list[str]] | None = None,
    pre_redacted_hint: tuple[str, list[str]] | None = None,
) -> tuple[AnalysisResponse, dict[str, Any]]:
    """Main flow. Returns (response, observability_meta).

    Scheduled as a dependency graph, not as stage barriers (research 09
    BE-2) — each step starts as soon as its inputs exist:

        t0 ── parse ──┬── deadline
           │          └── per rejection: retrieve ─┬─ draft ─ verify
           │                                       └─ element comparison ─┐
           └── claim tree ─────────────────────────────────────────────────┘

    Previously every stage waited for ALL rejections of the previous stage,
    and the claim tree, the deadline and the element comparison (one more
    round of model calls in local mode) sat behind the drafts.

    ``pre_redacted`` / ``pre_redacted_hint``: the gateway already redacted the
    OA and hint for the cache key — passing (text, rules) here avoids doing it
    twice (BE-7). Without them the orchestrator redacts itself (invariant #3).

    `circuit_open` is forwarded from the gateway cost circuit breaker (Q18):
    when True the AI Engine degrades the draft model to the cheap tier.
    """
    started = time.monotonic()
    # The id the user sees must be the one the logs carry: the request-id
    # middleware's bound X-Request-ID (also sent to the AI Engine). A fresh
    # uuid here made "analysis 3f2a… was slow" untraceable (FAILURE_LOG B-14).
    request_id = _user_facing_request_id()
    # One absolute deadline for the whole analysis, passed down every hop.
    deadline_at = time.time() + float(settings.ANALYZE_DEADLINE_SEC)
    ai = AIEngineClient(deadline=deadline_at)
    # Steps that fell back (saga) — any entry makes the result "degraded":
    # shown to the attorney, never cached (review V-B3).
    fallback_steps: list[str] = []
    # Resolved ONCE per analysis: every step of one request routes the same
    # way even if the registry file changes mid-request (invariant #7).
    security_level = security_level_for_case(req.case_id)
    case_jurisdiction = _jurisdiction_for_patent(req.target_patent_no)
    tenant = user.tenant_id

    # ---- Step 0: redact OA (+ hint) before anything leaves the gateway ----
    # (Q3 + Q10, invariant #3). Masking writes the mapping store (SQLite), so
    # it runs off the event loop (BE-6).
    t_redact = time.monotonic()
    redacted_here = False  # the gateway times its own redaction
    if pre_redacted is not None:
        redacted_oa, mask_rules_triggered = pre_redacted
    else:
        redacted_oa, mask_rules_triggered = await asyncio.to_thread(masking.redact, req.oa_text, tenant)
        redacted_here = True
    # The attorney's free-text hint goes to the same LLM — it gets the same
    # mandatory redaction (invariant #3).
    redacted_hint = None
    if req.user_hint:
        if pre_redacted_hint is not None:
            redacted_hint, hint_rules = pre_redacted_hint
        else:
            redacted_hint, hint_rules = await asyncio.to_thread(masking.redact, req.user_hint, tenant)
            redacted_here = True
        mask_rules_triggered = [*mask_rules_triggered, *hint_rules]
    if redacted_here:
        ai.record("redact", time.monotonic() - t_redact)

    # ---- t0: claim tree (needs only the patent number) ∥ parse ----
    async def _claim_tree() -> list[ClaimNode]:
        # Presentation nicety — a failure yields no tree, never a failed
        # analysis (but the result counts as degraded).
        try:
            ct_resp = await ai.call("/v1/claim_tree", {"tenant_id": tenant, "patent_no": req.target_patent_no})
            return [ClaimNode(**n) for n in ct_resp.get("claim_tree", [])]
        except Exception:  # noqa: BLE001 — CancelledError still propagates
            fallback_steps.append("claim_tree")
            return []

    async def _masked_claims() -> tuple[list[ClaimNode], list[dict]]:
        """The tree plus its claims redacted for element comparison (claim
        text leaves the gateway — invariant #3), computed once for every
        rejection."""
        nodes = await claim_tree_task
        if not (settings.CLAIM_ELEMENTS_ENABLED and nodes):
            return nodes, []

        def _mask() -> list[dict]:
            out = []
            for node in nodes:
                nd = node.model_dump()
                nd["text"], _ = masking.redact(nd["text"], tenant)
                out.append(nd)
            return out

        return nodes, await asyncio.to_thread(_mask)

    claim_tree_task = asyncio.create_task(_claim_tree())
    claims_task = asyncio.create_task(_masked_claims())
    deadline_task: asyncio.Task | None = None
    pipeline_tasks: list[asyncio.Task] = []
    try:
        # ---- Step 1: parse OA → identify rejections (required) ----
        parsed = await ai.call(
            "/v1/parse_oa",
            {
                "oa_text": redacted_oa,
                "tenant_id": tenant,
                "case_id": req.case_id,
                "target_patent_no": req.target_patent_no,
                "security_level": security_level,
            },
        )
        oa_doc = OADocument(**parsed["oa"])
        if parsed.get("output_unparseable"):
            fallback_steps.append("parse")

        # ---- Deadline (Q17): needs only the parse — starts now (required) ----
        deadline_task = asyncio.create_task(
            ai.call(
                "/v1/deadline",
                {
                    "received_date_iso": oa_doc.received_date.isoformat(),
                    "jurisdiction": case_jurisdiction,
                    "calendar_version": settings.HOLIDAY_CALENDAR_VERSION,
                    # Q16/Q17/Q19 deadline facts (optional; unknown -> earlier deadline)
                    "applicant_domestic": req.applicant_domestic,
                    "oa_sequence": req.oa_sequence,
                    "service_date_iso": req.service_date,
                    # redacted text only — for CN 第N次 / labelled 送達日 detection
                    "oa_text": redacted_oa[:20_000],
                },
            )
        )

        async def _element_tables(rej, hits: list[RetrievalHit]) -> list[ClaimElementTable]:
            # Q15/Q16: chart the rejected independent claim(s) against THIS
            # rejection's grounded hits. Runs alongside draft + verify.
            _, masked_claims = await claims_task
            if not masked_claims:
                return []
            try:
                et = await ai.call(
                    "/v1/element_comparison",
                    {
                        "tenant_id": tenant,
                        "rejection": rej.model_dump(),
                        "claims": masked_claims,
                        "grounded_set": [h.model_dump() for h in hits],
                        "security_level": security_level,
                        "target_patent_no": req.target_patent_no,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "element comparison failed for rejection %s (%s) — no table",
                    rej.rejection_id,
                    exc.__class__.__name__,
                )
                fallback_steps.append("element_comparison")
                return []
            tables = []
            for t in et.get("tables", []):
                try:
                    tables.append(ClaimElementTable(**t))
                except (TypeError, ValueError):
                    continue
            return tables

        async def _pipeline(rej) -> dict[str, Any]:
            """retrieve → draft → verify for ONE rejection (saga: a failure
            degrades this rejection only)."""
            calls: list[dict] = []  # successful AI-Engine replies, for cost
            # -- retrieve (Q1+FU: a failed retrieval → empty grounded set) --
            hits: list[RetrievalHit] = []
            try:
                ret = await ai.call(
                    "/v1/retrieve_prior_art",
                    {
                        "tenant_id": tenant,
                        "rejection": rej.model_dump(),
                        "target_patent_no": req.target_patent_no,
                        "top_k": 5,
                        # Filing/priority date hard-excludes art published on
                        # or after it (專利法 §22/§23); None = no date filter.
                        "filing_date": req.filing_date,
                    },
                )
                calls.append(ret)
                hits = [RetrievalHit(**h) for h in ret["hits"]]
                # [GROUNDED_REF_n] is numbered per rejection (1-based into
                # THIS list); tag each hit so the SPA can resolve a citation
                # pill once all rejections' hits are flattened.
                for i, h in enumerate(hits):
                    h.metadata = {**h.metadata, "rejection_id": rej.rejection_id, "ref_index": i + 1}
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "saga: retrieval failed for rejection %s (%s) — proceeding with empty grounded set",
                    rej.rejection_id,
                    exc.__class__.__name__,
                )
                fallback_steps.append("retrieve")
                hits = []

            element_task = asyncio.create_task(_element_tables(rej, hits))
            try:
                # -- draft (Q14: only the grounded set may be cited) --
                draft: DraftResponse | None = None
                try:
                    dr = await ai.call(
                        "/v1/draft_response",
                        {
                            "tenant_id": tenant,
                            "user_id": user.user_id,
                            "case_id": req.case_id,
                            "rejection": rej.model_dump(),
                            "grounded_set": [h.model_dump() for h in hits],
                            "user_hint": redacted_hint,
                            "security_level": security_level,
                            "circuit_open": circuit_open,
                        },
                    )
                    calls.append(dr)
                    if dr.get("output_unparseable"):
                        fallback_steps.append("draft")
                    draft = DraftResponse(**dr["draft"])
                except (KeyError, TypeError, ValueError) as exc:
                    # Malformed AI Engine reply for this rejection.
                    logger.warning(
                        "saga: malformed draft payload for rejection %s (%s) — "
                        "emitting degraded placeholder",
                        rej.rejection_id,
                        exc.__class__.__name__,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "saga: draft generation failed for rejection %s (%s) — "
                        "emitting degraded placeholder",
                        rej.rejection_id,
                        exc.__class__.__name__,
                    )

                # -- verify (Q14 third defence) — only a draft that exists --
                if draft is not None:
                    try:
                        v = await ai.call(
                            "/v1/verify_citations",
                            {
                                "draft": draft.model_dump(),
                                "grounded_set": [h.model_dump() for h in hits],
                                "jurisdiction": case_jurisdiction,
                                # The verifier sees the (redacted) draft too —
                                # a confidential case stays local (invariant #7).
                                "security_level": security_level,
                            },
                        )
                        calls.append(v)
                        # Verifier-cleaned text + transparency fields (what was
                        # stripped, confidence, which model verified).
                        draft.draft_text = v["cleaned_draft_text"]
                        draft.grounded_citations = v["valid_citations"]
                        draft.invalid_citations = v.get("invalid_citations", [])
                        draft.verifier_confidence = v.get("verifier_confidence")
                        draft.verifier_model = v.get("model_used")
                        # Q14/Q17 sentence-level alignment (unsupported refs are
                        # already [UNSUPPORTED_REF_n] in cleaned_draft_text).
                        draft.alignment = [SentenceAlignment(**r) for r in v.get("alignment", [])]
                        draft.unsupported_citations = v.get("unsupported_citations", [])
                        draft.confidence = min(draft.confidence, v["verifier_confidence"])
                    except Exception as exc:  # noqa: BLE001
                        # Q14 hard wall: an unverified draft must NOT be served
                        # with its (unvalidated) citations.
                        logger.warning(
                            "saga: citation verification failed for rejection %s (%s) — "
                            "emitting degraded placeholder",
                            rej.rejection_id,
                            exc.__class__.__name__,
                        )
                        draft = None
                tables = await element_task
            finally:
                # Cancelled mid-draft (the analysis failed elsewhere): stop the
                # element comparison too, and read its outcome even if it had
                # already failed — no "exception never retrieved" (W2-A5).
                await _cancel_and_drain(element_task)
            return {
                "hits": hits,
                "draft": draft if draft is not None else _degraded_draft(rej.rejection_id),
                "tables": tables,
                "calls": calls,
            }

        pipeline_tasks = [asyncio.create_task(_pipeline(r)) for r in oa_doc.rejections]
        # Fail fast: the deadline is required — if it fails, stop the drafts
        # now instead of letting them finish for an analysis that will 5xx.
        # (Plain tasks, no gather(): a cancelled gather future carries an
        # exception nobody retrieves — logged on every failed analysis.)
        required = (deadline_task, *pipeline_tasks)
        await asyncio.wait(required, return_when=asyncio.FIRST_EXCEPTION)
        for t in required:
            if t.done() and not t.cancelled() and t.exception() is not None:
                t.result()  # re-raise the first failure
        deadline_resp = deadline_task.result()
        results = [t.result() for t in pipeline_tasks]
        claim_tree_nodes, _ = await claims_task
    except BaseException:
        await _cancel_and_drain(claim_tree_task, claims_task, deadline_task, *pipeline_tasks)
        raise

    deadline = DeadlineInfo(**deadline_resp)
    oa_doc.deadline = deadline.statutory_deadline

    # Assemble in rejection order (the SPA and the citation numbering rely on it).
    all_hits: list[RetrievalHit] = []
    drafts: list[DraftResponse] = []
    element_tables: list[ClaimElementTable] = []
    pipeline_calls: list[dict] = []
    for r in results:
        all_hits.extend(r["hits"])
        drafts.append(r["draft"])
        element_tables.extend(r["tables"])
        pipeline_calls.extend(r["calls"])

    # ---- Un-mask outbound for the attorney's eyes (mapping store → thread) ----
    t_unmask = time.monotonic()

    def _unmask_all() -> None:
        for table in element_tables:
            for row in table.elements:
                row.text = masking.unmask(row.text, tenant)
        for d in drafts:
            d.draft_text = masking.unmask(d.draft_text, tenant)
            d.strategy = masking.unmask(d.strategy, tenant)

    await asyncio.to_thread(_unmask_all)
    ai.record("unmask", time.monotonic() - t_unmask)

    # ---- Aggregate cost ----
    # Each AI engine reply carries an Anthropic-style usage dict (zeros for
    # mock / Ollama cache fields). estimate_cost() per call against its own
    # model_used, then sum — keeps cache-discount accuracy intact. Only
    # successful replies are here (a failed call produced no billable usage).
    all_call_meta = [parsed, *pipeline_calls]
    total_prompt_tokens = sum(r.get("usage", {}).get("prompt_tokens", 0) for r in all_call_meta)
    total_completion_tokens = sum(
        r.get("usage", {}).get("completion_tokens", 0) for r in all_call_meta
    )

    estimated_cost = 0.0
    # M-3 fix: track the *weakest* provenance across every call. Order is
    # exact > fallback > mock (where "weakest" = least trustworthy for
    # billing). If any LLM call dispatched to a fallback-priced model, the
    # aggregate cost is suspect even if other calls were exact-priced.
    _provenance_rank = {"exact": 0, "mock": 1, "fallback": 2}
    worst_provenance = "exact"
    for r in all_call_meta:
        usage = r.get("usage") or {}
        model = r.get("model_used", "mock")
        # Skip pricing for retrieval (no LLM call) — its usage row is all zeros anyway.
        if not usage:
            continue
        call_cost = estimate_cost(model, usage)
        estimated_cost += call_cost
        prov = cost_provenance_for(model)
        # Spend metric per call, under that call's own model, and only for
        # exact pricing (review V-B7).
        if prov == "exact" and call_cost > 0:
            metrics.LLM_COST_USD.inc({"tenant": tenant, "model": str(model)[:64]}, float(call_cost))
        if _provenance_rank.get(prov, 99) > _provenance_rank.get(worst_provenance, -1):
            worst_provenance = prov

    cost_meta = CostMeta(
        prompt_tokens=total_prompt_tokens,
        completion_tokens=total_completion_tokens,
        # Surface degradation from ANY step, not just parse: the SPA's degraded
        # banner keys on "-DEGRADED-" in this label, and a draft-only fallback
        # to mock must not look like a real model's output.
        model=next(
            (
                r.get("model_used")
                for r in all_call_meta
                if "-DEGRADED-" in str(r.get("model_used") or "")
            ),
            parsed.get("model_used", "mock"),
        ),
        estimated_cost_usd=estimated_cost,
        cache_hit=False,
        cost_provenance=worst_provenance,
    )

    # CHUNK-8 trust band — "N entities masked" on THIS analysis; rule ids
    # de-duplicated so the tooltip lists types without re-revealing values.
    redaction_summary = RedactionSummary(
        masked_entity_count=len(mask_rules_triggered),
        rules_triggered=sorted(set(mask_rules_triggered)),
    )

    response = AnalysisResponse(
        request_id=request_id,
        oa=oa_doc,
        drafts=drafts,
        related_prior_art=all_hits,
        deadline_summary=deadline,
        cost_meta=cost_meta,
        claim_tree=claim_tree_nodes,
        element_tables=element_tables,
        redaction_summary=redaction_summary,
    )

    duration_ms = int((time.monotonic() - started) * 1000)
    obs = {
        "duration_ms": duration_ms,
        "mask_rules": mask_rules_triggered,
        "model_used": cost_meta.model,
        "prompt_tokens": cost_meta.prompt_tokens,
        "completion_tokens": cost_meta.completion_tokens,
        "estimated_cost_usd": cost_meta.estimated_cost_usd,
        # Any step fell back (mock model, saga placeholder, empty retrieval
        # after an error, unparseable model output, missing claim tree or
        # element table): the result is shown, but must never be cached — a
        # short outage would otherwise be served from cache for the whole TTL
        # (FAILURE_LOG B-15, review V-B3).
        "degraded": is_degraded_response(response) or bool(fallback_steps),
        "fallback_steps": sorted(set(fallback_steps)),
        # OBS-3: per-stage time (longest call per stage) for Server-Timing.
        "stage_ms": {**ai.stage_ms(), "total": duration_ms},
    }
    return response, obs


_DEGRADED_NOTE = "[draft generation failed for this rejection — manual attorney drafting required]"


def is_degraded_response(response: AnalysisResponse) -> bool:
    """True if any part of the analysis came from a fallback path."""
    if "-DEGRADED-" in str(response.cost_meta.model or ""):
        return True
    return any(d.draft_text == _DEGRADED_NOTE for d in response.drafts)


def _degraded_draft(rejection_id: str) -> DraftResponse:
    """Saga fallback (Q1 + Follow-up): a placeholder draft for a rejection
    whose draft / verify step failed.

    Confidence is pinned to 0.0 and citations are empty so the front-end and
    the attorney treat it as "AI could not help here — draft manually". The
    rest of the analysis (other rejections, deadline, claim tree) is unaffected.
    """
    return DraftResponse(
        rejection_id=rejection_id,
        strategy=_DEGRADED_NOTE,
        draft_text=_DEGRADED_NOTE,
        grounded_citations=[],
        confidence=0.0,
        requires_attorney_review=True,
    )


_KNOWN_JURISDICTIONS = {"US", "TW", "EP", "JP", "CN", "KR"}


def _jurisdiction_for_patent(patent_no: str) -> str:
    """Q17: the answer period + holiday calendar differ per jurisdiction, so
    a US patent must NOT be scored against TW's 60-day rule (and vice versa).
    Also drives cross-jurisdiction citation-leak detection in verify_citations
    (a TW 申復書 must not cite 35 U.S.C.) — so a wrong code mis-routes that gate.

    POC: derive from the patent-number country/office code, taken as the LEADING
    RUN OF LETTERS (so "TWI123456" → TW, "US-9999999" → US, but a bare numeric
    "1234567" cleanly falls through instead of coincidentally matching its first
    two digits). PCT publications ("WO…") have no single national response period,
    so they route to the firm's home office. Anything unrecognised / missing also
    falls back to TW; the deadline module additionally warns for any jurisdiction
    it can't compute. Production: read jurisdiction from the case-management
    record rather than parsing the number.
    """
    if not patent_no:
        return "TW"
    s = patent_no.strip().upper()
    i = 0
    while i < len(s) and s[i].isascii() and s[i].isalpha():
        i += 1
    code = s[:i][:2]  # leading letters, first two (the ISO-ish country/office code)
    if code in _KNOWN_JURISDICTIONS:
        return code
    # WO = PCT international phase; route to home office for deadline purposes.
    return "TW"
