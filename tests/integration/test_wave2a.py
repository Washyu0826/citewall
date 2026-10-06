"""Optimisation wave 2a (docs/research/09): DAG scheduling (BE-2), one
analysis deadline passed down every hop (BE-4), blocking I/O off the event
loop (BE-6) incl. the audit read connection (M-13), redaction batched and done
once (BE-7), single-flight (BE-9), Redis timeouts (BE-12), warm-up and
readiness (BE-13 / OBS-9), per-stage timing (OBS-3).

Everything that can runs through the real gateway and the in-process AI
Engine (mock LLM).
"""

from __future__ import annotations

import asyncio
import contextvars
import gc
import inspect
import json
import logging
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.gateway import audit, masking, rate_limit
from backend.gateway import cache as cache_mod
from backend.gateway import main as gw_main
from backend.gateway import orchestrator as orch
from backend.shared import metrics, readiness, time_budget
from backend.shared import observability as obs
from backend.shared.config import settings

_OA = (Path(__file__).resolve().parents[2] / "data" / "oa_samples" / "sample_oa_us.txt").read_text(
    encoding="utf-8"
)


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(cache_mod, "_cache", cache_mod._MemoryCache())


def _analyze(client, token, *, request_id=None, hint=None):
    headers = {"Authorization": f"Bearer {token}"}
    if request_id:
        headers[obs.REQUEST_ID_HEADER] = request_id
    body = {"oa_text": _OA, "case_id": "CASE-2025-001", "target_patent_no": "US17123456"}
    if hint:
        body["user_hint"] = hint
    return client.post("/v1/oa/analyze", headers=headers, json=body)


def _stage_count(stage: str, outcome: str = "ok") -> float:
    total = 0.0
    for key, _buckets, _sum, count in metrics.ANALYZE_STAGE_DURATION._snapshot():
        labels = dict(key)
        if labels.get("stage") == stage and labels.get("outcome") == outcome:
            total += count
    return total


def _counter_total(counter) -> float:
    return sum(v for _, v in counter._snapshot())


def _wait_until(pred, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def _last_analyze_audit_rows(n: int) -> list[tuple]:
    return audit.writer._fetchall(
        "SELECT model_used, policy_decisions FROM audit WHERE endpoint = ? "
        "ORDER BY rowid DESC LIMIT ?",
        ("/v1/oa/analyze", n),
    )


# ---------------------------------------------------------------------------
# OBS-3: per-stage time — metric + Server-Timing
# ---------------------------------------------------------------------------
def test_each_stage_is_timed_and_reported_in_server_timing(
    gateway_client, alice_token, patched_ai_engine
):
    before = {s: _stage_count(s) for s in ("redact", "parse", "retrieve", "draft", "verify", "deadline")}
    resp = _analyze(gateway_client, alice_token)
    assert resp.status_code == 200, resp.text
    for stage, n in before.items():
        assert _stage_count(stage) > n, f"no {stage} sample"
    timing = resp.headers["Server-Timing"]
    for name in ("redact", "parse", "draft", "verify", "deadline", "total"):
        assert f"{name};dur=" in timing, timing

    again = _analyze(gateway_client, alice_token)
    assert again.json()["cost_meta"]["cache_hit"] is True
    assert "cache;desc=hit" in again.headers["Server-Timing"]


def test_server_timing_carries_only_stage_names_and_durations():
    header = gw_main._server_timing({"parse": 12, "Bad Name": 3, "x" * 40: 1, "draft": 7.9}, "coalesced")
    assert header == "parse;dur=12, draft;dur=7, coalesced"


# ---------------------------------------------------------------------------
# BE-7: the OA is redacted once per analysis, mappings in one transaction
# ---------------------------------------------------------------------------
def test_the_oa_is_redacted_once_per_analysis(monkeypatch, gateway_client, alice_token, patched_ai_engine):
    seen = []
    real = masking.redact

    def spy(text, tenant_id):
        if text == _OA:
            seen.append(1)
        return real(text, tenant_id)

    monkeypatch.setattr(masking, "redact", spy)
    resp = _analyze(gateway_client, alice_token)
    assert resp.status_code == 200, resp.text
    assert len(seen) == 1


def test_one_redaction_writes_its_mappings_in_one_transaction(monkeypatch, tmp_path):
    store = masking.MaskingStore(path=tmp_path / "mapping.db")
    monkeypatch.setattr(masking, "_store", store)
    statements: list[str] = []
    store._conn.set_trace_callback(statements.append)
    text = "Contact alice@example.com or bob@example.org, tel 0912-345-678; alice@example.com again."
    redacted, rules = masking.redact(text, "tenant_a")
    store._conn.set_trace_callback(None)

    assert "alice@example.com" not in redacted and "0912-345-678" not in redacted
    assert sum(s.strip().upper() == "COMMIT" for s in statements) == 1
    # One row per distinct value (the repeated e-mail is stored once) …
    placeholders = set(re.findall(r"\[[A-Z_]+_[0-9A-F]{8}\]", redacted))
    assert len(placeholders) >= 3
    assert sum(s.upper().startswith("INSERT") for s in statements) == len(placeholders)
    # … and every placeholder still un-masks.
    assert masking.unmask(redacted, "tenant_a") == masking.normalize_for_detection(text)


def test_a_failed_mapping_batch_leaves_no_open_transaction(tmp_path):
    store = masking.MaskingStore(path=tmp_path / "mapping.db")
    store._conn.execute("CREATE TRIGGER boom BEFORE INSERT ON mappings BEGIN SELECT RAISE(ABORT, 'x'); END")
    store._conn.commit()
    with pytest.raises(sqlite3.DatabaseError):
        store.remember_many("tenant_a", [("[EMAIL_00000001]", "a@b.co", "email")])
    assert not store._conn.in_transaction


# ---------------------------------------------------------------------------
# BE-4: one analysis deadline, passed down every hop
# ---------------------------------------------------------------------------
def test_the_ai_engine_sees_the_analysis_deadline(monkeypatch, gateway_client, alice_token, patched_ai_engine):
    from backend.ai_engine import oa_analyzer

    seen = []
    real = oa_analyzer.parse_oa

    def spy(*args, **kwargs):
        seen.append(time_budget.current_deadline())
        return real(*args, **kwargs)

    monkeypatch.setattr(oa_analyzer, "parse_oa", spy)
    started = time.time()
    resp = _analyze(gateway_client, alice_token)
    assert resp.status_code == 200, resp.text
    assert seen and seen[0] is not None
    assert abs(seen[0] - (started + settings.ANALYZE_DEADLINE_SEC)) < 10


def test_a_spent_deadline_is_a_504_with_audit_row_and_quota_back(
    monkeypatch, gateway_client, alice_token, patched_ai_engine
):
    monkeypatch.setattr(settings, "ANALYZE_DEADLINE_SEC", 1.0)  # < the 2 s minimum per call
    released = []
    real_record = rate_limit.record_usage

    def spy(user, *args, **kwargs):
        released.append((args, kwargs))
        return real_record(user, *args, **kwargs)

    monkeypatch.setattr(rate_limit, "record_usage", spy)
    resp = _analyze(gateway_client, alice_token, request_id="trace-deadline-504")
    assert resp.status_code == 504, resp.text
    model_used, pd = _last_analyze_audit_rows(1)[0]
    assert model_used is None and '"error": true' in pd
    assert released and released[-1][0] == (0, 0, 0.0)


async def test_an_engine_call_that_times_out_is_a_504_and_counted(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("slow engine", request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        orch.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    client = orch.AIEngineClient("http://engine.test", deadline=time.time() + 60)
    before = _stage_count("parse", "timeout")
    with pytest.raises(orch.AnalysisTimeout) as exc:
        await client.call("/v1/parse_oa", {"oa_text": "Claims 1-3 are rejected."})
    assert exc.value.status_code == 504
    assert _stage_count("parse", "timeout") == before + 1


def test_the_engine_running_out_of_time_in_a_required_step_is_a_504(
    monkeypatch, gateway_client, alice_token, patched_ai_engine
):
    """W2-A6/B4: BudgetExhausted inside the engine used to escape as a 500
    (anthropic) or turn into labelled mock text (local / dify)."""
    from backend.ai_engine import oa_analyzer

    def spent(*args, **kwargs):
        raise time_budget.BudgetExhausted("request deadline leaves 0.4s")

    monkeypatch.setattr(oa_analyzer, "parse_oa", spent)
    errors_before = _counter_total(metrics.LLM_ERRORS)
    timeouts_before = _stage_count("parse", "timeout")
    resp = _analyze(gateway_client, alice_token)
    assert resp.status_code == 504, resp.text
    assert _stage_count("parse", "timeout") == timeouts_before + 1
    assert _counter_total(metrics.LLM_ERRORS) == errors_before  # a deadline, not a model failure


def test_the_engine_running_out_of_time_in_a_draft_degrades_that_rejection(
    monkeypatch, gateway_client, alice_token, patched_ai_engine
):
    from backend.ai_engine import oa_analyzer

    def spent(*args, **kwargs):
        raise time_budget.BudgetExhausted("request deadline leaves 0.4s")

    monkeypatch.setattr(oa_analyzer, "draft_response", spent)
    resp = _analyze(gateway_client, alice_token)
    assert resp.status_code == 200, resp.text
    drafts = resp.json()["drafts"]
    assert drafts and all(d["draft_text"] == orch._DEGRADED_NOTE for d in drafts)
    again = _analyze(gateway_client, alice_token)
    assert again.json()["cost_meta"]["cache_hit"] is False  # degraded: never cached


def _in_context(fn):
    """Run ``fn`` in a copy of the current context, so request-id / deadline
    bindings made inside never leak into later tests."""
    return contextvars.copy_context().run(fn)


def _ollama_reply(url):
    body = {"choices": [{"message": {"content": "{}"}}], "usage": {}}
    return httpx.Response(200, json=body, request=httpx.Request("POST", url))


def test_local_model_waits_take_the_time_left(monkeypatch):
    from backend.ai_engine import llm_client

    timeouts = []

    def fake_post(url, **kwargs):
        timeouts.append(kwargs["timeout"])
        return _ollama_reply(url)

    monkeypatch.setattr(settings, "LLM_MODE", "local")
    monkeypatch.setattr(httpx, "post", fake_post)

    def call():
        time_budget.bind_deadline(time.time() + 12)
        return llm_client.chat(system="s", user="u", intent="parse_oa", security_level="public")

    reply = _in_context(call)
    assert 9 <= timeouts[0] <= 10
    assert "DEGRADED" not in reply.model


def test_local_mode_out_of_time_raises_instead_of_answering_with_mock_text(monkeypatch):
    from backend.ai_engine import llm_client

    def capped_wait_fires(url, **kwargs):
        time_budget.bind_deadline(time.time() + 2.5)  # the capped wait used the budget up
        raise httpx.ReadTimeout("no reply", request=httpx.Request("POST", url))

    monkeypatch.setattr(settings, "LLM_MODE", "local")
    monkeypatch.setattr(httpx, "post", capped_wait_fires)

    def spent_before_the_call():
        time_budget.bind_deadline(time.time() + 2.5)
        return llm_client.chat(system="s", user="u", intent="parse_oa", security_level="public")

    def spent_during_the_call():
        time_budget.bind_deadline(time.time() + 60)
        return llm_client.chat(system="s", user="u", intent="parse_oa", security_level="public")

    with pytest.raises(time_budget.BudgetExhausted):
        _in_context(spent_before_the_call)
    with pytest.raises(time_budget.BudgetExhausted):
        _in_context(spent_during_the_call)


def test_local_mode_still_degrades_when_ollama_is_slow_within_its_own_timeout(monkeypatch):
    from backend.ai_engine import llm_client

    def slow(url, **kwargs):
        raise httpx.ReadTimeout("no reply", request=httpx.Request("POST", url))

    monkeypatch.setattr(settings, "LLM_MODE", "local")
    monkeypatch.setattr(httpx, "post", slow)

    def call():
        time_budget.bind_deadline(time.time() + 300)
        return llm_client.chat(system="s", user="u", intent="parse_oa", security_level="public")

    assert "-DEGRADED-" in _in_context(call).model


class _FakeDify:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[dict] = []

    def post(self, url, json, headers, timeout):
        self.calls.append({"user": json["user"], "timeout": timeout})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return httpx.Response(200, json=self.outcome, request=httpx.Request("POST", url))


def test_dify_calls_take_the_time_left_and_never_send_the_raw_request_id():
    from backend.ai_engine import llm_client

    dify = _FakeDify({"data": {"status": "succeeded", "outputs": {"text": "{}"}}})
    llm = llm_client.DifyLLM(api_url="http://dify.test", api_key="k", client=dify)

    def call():
        obs.bind_request_id("trace-陳小華-0912")
        time_budget.bind_deadline(time.time() + 12)
        return llm.chat("s", "u", "parse_oa", "m")

    reply = _in_context(call)
    assert "DEGRADED" not in reply.model
    sent = dify.calls[0]
    assert 9 <= sent["timeout"] <= 10
    assert sent["user"] == llm_client.dify_user_for("trace-陳小華-0912")
    assert "陳" not in sent["user"] and "0912" not in sent["user"] and "trace" not in sent["user"]
    assert llm_client.dify_user_for("trace-other") != sent["user"]
    assert llm_client.dify_user_for(None) == "patent-oa-assistant-gateway"


def test_dify_out_of_time_raises_instead_of_answering_with_mock_text():
    from backend.ai_engine import llm_client

    llm = llm_client.DifyLLM(api_url="http://dify.test", api_key="k", client=_FakeDify({}))

    def call():
        time_budget.bind_deadline(time.time() + 2.5)
        return llm.chat("s", "u", "parse_oa", "m")

    with pytest.raises(time_budget.BudgetExhausted):
        _in_context(call)


def _anthropic_client(error):
    attempts = []

    class _Messages:
        async def create(self, **kwargs):
            attempts.append(kwargs.get("timeout"))
            raise error

    class _Client:
        messages = _Messages()

    return _Client(), attempts


async def test_anthropic_stops_retrying_when_no_attempt_fits_but_keeps_the_real_error():
    """No retry fits in the deadline: give up at once — with the provider's
    error (a 500 counted in llm_errors_total), not a deadline 504 that would
    hide an outage late in an analysis (review W2-C5)."""
    import anthropic

    from backend.ai_engine import llm_client

    client, attempts = _anthropic_client(
        anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.test"))
    )
    time_budget.bind_deadline(time.time() + 8)
    try:
        with pytest.raises(anthropic.APIConnectionError):
            await llm_client._call_with_retry(client, max_retries=3, model="m")
    finally:
        time_budget.bind_deadline(None)
    assert len(attempts) == 1, "retried although no attempt could finish in time"
    assert attempts[0] <= 6  # the attempt's own timeout was capped by the deadline


async def test_anthropic_timeout_capped_by_the_deadline_is_a_deadline():
    import anthropic

    from backend.ai_engine import llm_client

    attempts = []

    class _Messages:
        async def create(self, **kwargs):
            attempts.append(kwargs["timeout"])
            time_budget.bind_deadline(time.time() + 2.5)  # the capped wait used the budget up
            raise anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.test"))

    class _Client:
        messages = _Messages()

    time_budget.bind_deadline(time.time() + 60)
    try:
        with pytest.raises(time_budget.BudgetExhausted):
            await llm_client._call_with_retry(_Client(), max_retries=3, model="m")
    finally:
        time_budget.bind_deadline(None)
    assert len(attempts) == 1


def test_local_verifier_out_of_time_uses_the_default_verifier_not_a_counted_failure(monkeypatch):
    """With LOCAL_VERIFIER_MODEL set, running out of time used to be logged
    and counted as a model failure (-verifier-fallback) — W2-C6."""
    from backend.ai_engine import llm_client

    monkeypatch.setattr(settings, "LLM_MODE", "local")
    monkeypatch.setattr(settings, "LOCAL_VERIFIER_MODEL", "some-other-local-model")

    def capped_wait_fires(url, **kwargs):
        time_budget.bind_deadline(time.time() + 2.5)
        raise httpx.ReadTimeout("no reply", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", capped_wait_fires)

    def call():
        time_budget.bind_deadline(time.time() + 60)
        return llm_client.chat(system="s", user="u", intent="verify_citations", security_level="public")

    assert _in_context(call).model == "local-verifier-mock"


def test_claim_decomposition_out_of_time_is_not_served_as_a_rule_split(monkeypatch):
    """A rule split served on a deadline would be cached as if the LLM
    decomposer had run; out of time must surface (→ 504 → degraded, not
    cached) — W2-C6."""
    from backend.ai_engine import claim_elements, llm_client

    def spent(**kwargs):
        raise time_budget.BudgetExhausted("request deadline leaves 0.4s")

    monkeypatch.setattr(claim_elements, "_llm_enabled", lambda: True)
    monkeypatch.setattr(llm_client, "chat", spent)
    with pytest.raises(time_budget.BudgetExhausted):
        claim_elements.decompose("A widget comprising a gear and a shaft.", security_level="public")


def _mock_engine(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        orch.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )


async def test_a_stopped_call_is_counted_as_cancelled_not_as_an_error(monkeypatch):
    """W2-A7: when the analysis fails elsewhere, the calls it stops are not
    this step's errors — they inflated the error panel."""

    async def slow(request):
        await asyncio.sleep(30)

    _mock_engine(monkeypatch, slow)
    client = orch.AIEngineClient("http://engine.test", deadline=time.time() + 60)
    errors_before, cancelled_before = _stage_count("draft", "error"), _stage_count("draft", "cancelled")
    task = asyncio.create_task(client.call("/v1/draft_response", {"rejection": {}}))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _stage_count("draft", "cancelled") == cancelled_before + 1
    assert _stage_count("draft", "error") == errors_before


async def test_a_call_with_no_time_left_is_counted_as_a_timeout(monkeypatch):
    _mock_engine(monkeypatch, lambda request: pytest.fail("a call started with no time left"))
    client = orch.AIEngineClient("http://engine.test", deadline=time.time() + 1)
    before = _stage_count("verify", "timeout")
    with pytest.raises(orch.AnalysisTimeout):
        await client.call("/v1/verify_citations", {"draft": {}})
    assert _stage_count("verify", "timeout") == before + 1


async def test_the_engine_gets_seconds_left_not_a_clock_time(monkeypatch):
    seen = {}

    def handler(request):
        seen["budget"] = request.headers.get("X-Time-Budget")
        return httpx.Response(200, json={})

    _mock_engine(monkeypatch, handler)
    await orch.AIEngineClient("http://engine.test", deadline=time.time() + 40).call("/v1/deadline", {})
    assert 38 <= float(seen["budget"]) <= 40


def test_a_call_never_waits_past_the_deadline():
    client = orch.AIEngineClient("http://engine.test", deadline=time.time() + 30)
    assert client._timeout("/v1/parse_oa") <= 30
    with pytest.raises(orch.AnalysisTimeout):
        orch.AIEngineClient("http://engine.test", deadline=time.time() + 1)._timeout("/v1/parse_oa")


def test_model_waits_take_the_time_left(monkeypatch):
    time_budget.bind_deadline(time.time() + 12)
    try:
        assert 9 <= time_budget.budget(300) <= 10
        assert time_budget.can_afford(5) and not time_budget.can_afford(20)
        time_budget.bind_deadline(time.time() + 2.5)
        with pytest.raises(time_budget.BudgetExhausted):
            time_budget.budget(300)
    finally:
        time_budget.bind_deadline(None)
    assert time_budget.budget(300) == 300  # no request deadline → own default


def test_the_budget_travels_as_seconds_left_not_a_clock_time():
    """Relative on the wire, so the two hosts' clocks need not agree (W2-B6)."""
    now = 1_000_000.0
    assert time_budget.format_budget(now + 42.5, now=now) == "42.500"
    assert time_budget.format_budget(now - 5, now=now) == "0.000"
    # The engine turns it into a deadline on ITS clock.
    assert time_budget.parse_budget("42.5", now=5.0) == pytest.approx(47.5)
    # Spent budgets stay spent — never "no deadline".
    assert time_budget.parse_budget("0", now=5.0) == pytest.approx(5.0)
    assert time_budget.parse_budget("-3", now=5.0) == pytest.approx(5.0)
    for nonsense in ("garbage", "nan", "inf", "7200", ""):
        assert time_budget.parse_budget(nonsense, now=5.0) is None, nonsense


# ---------------------------------------------------------------------------
# BE-2: dependency-graph scheduling
# ---------------------------------------------------------------------------
def _record_calls(monkeypatch, delays: dict[str, float], fail: set[str] = frozenset()):
    log: list[tuple[str, str, float]] = []
    real_call = orch.AIEngineClient.call

    async def call(self, path, payload):
        log.append(("start", path, time.monotonic()))
        try:
            if path in delays:
                await asyncio.sleep(delays[path])
            if path in fail:
                raise RuntimeError(f"{path} down")
            return await real_call(self, path, payload)
        except asyncio.CancelledError:
            log.append(("cancelled", path, time.monotonic()))
            raise
        finally:
            log.append(("end", path, time.monotonic()))

    monkeypatch.setattr(orch.AIEngineClient, "call", call)
    return log


def _first(log, event, path):
    return min(t for e, p, t in log if e == event and p == path)


def _last(log, event, path):
    return max(t for e, p, t in log if e == event and p == path)


def test_independent_steps_do_not_wait_for_each_other(monkeypatch, gateway_client, alice_token, patched_ai_engine):
    log = _record_calls(monkeypatch, {"/v1/parse_oa": 0.3, "/v1/draft_response": 0.4})
    resp = _analyze(gateway_client, alice_token)
    assert resp.status_code == 200, resp.text
    # The claim tree needs only the patent number: it runs during the parse.
    assert _first(log, "start", "/v1/claim_tree") < _last(log, "end", "/v1/parse_oa")
    # The deadline needs only the parse: it does not wait for the drafts.
    assert _first(log, "start", "/v1/deadline") < _last(log, "end", "/v1/draft_response")


def test_a_failed_deadline_stops_the_drafts_instead_of_waiting(
    monkeypatch, caplog, gateway_app, alice_token, patched_ai_engine
):
    # The deadline fails once the drafts are under way.
    log = _record_calls(
        monkeypatch, {"/v1/deadline": 0.5, "/v1/draft_response": 20.0}, fail={"/v1/deadline"}
    )
    started = time.monotonic()
    with caplog.at_level(logging.ERROR, logger="asyncio"):
        with TestClient(gateway_app, raise_server_exceptions=False) as client:
            resp = _analyze(client, alice_token)
        gc.collect()  # "never retrieved" is reported when the future is collected
    assert resp.status_code == 500
    assert time.monotonic() - started < 10, "waited for the drafts of a failed analysis"
    assert any(e == "cancelled" and p == "/v1/draft_response" for e, p, _ in log)
    leaked = [r.getMessage() for r in caplog.records if "never retrieved" in r.getMessage()]
    assert not leaked, leaked


# ---------------------------------------------------------------------------
# BE-9: single-flight
# ---------------------------------------------------------------------------
def _hold_orchestration(monkeypatch, *, fail_with: Exception | None = None):
    release = threading.Event()
    calls: list[int] = []
    real = gw_main.orchestrate_analysis

    async def held(*args, **kwargs):
        calls.append(1)
        while not release.is_set():
            await asyncio.sleep(0.01)
        if fail_with is not None:
            raise fail_with
        return await real(*args, **kwargs)

    monkeypatch.setattr(gw_main, "orchestrate_analysis", held)
    return release, calls


def _spy_usage(monkeypatch) -> list[tuple[tuple, dict]]:
    usage: list[tuple[tuple, dict]] = []
    real = rate_limit.record_usage

    def spy(user, *args, **kwargs):
        usage.append((args, kwargs))
        return real(user, *args, **kwargs)

    monkeypatch.setattr(rate_limit, "record_usage", spy)
    return usage


def _run_two(client, token, release, *, second_hint=None, expect_flights=1):
    """Start two analyses; return once both are in flight (the orchestration
    is held until ``release``). Releases on failure so no thread hangs."""
    pool = ThreadPoolExecutor(2)
    try:
        first = pool.submit(_analyze, client, token, request_id="sf-leader")
        assert _wait_until(lambda: len(gw_main._inflight_analyses) == 1)
        second = pool.submit(_analyze, client, token, request_id="sf-second", hint=second_hint)
        if expect_flights == 1:
            flight = next(iter(gw_main._inflight_analyses.values()))
            assert _wait_until(lambda: flight.waiters == 2), "second request never joined"
        else:
            assert _wait_until(lambda: len(gw_main._inflight_analyses) == expect_flights)
    except BaseException:
        release.set()
        pool.shutdown(wait=True)
        raise
    release.set()
    a, b = first.result(30), second.result(30)
    pool.shutdown()
    return a, b


def test_an_identical_concurrent_analysis_joins_the_running_one(
    monkeypatch, gateway_client, alice_token, patched_ai_engine
):
    release, calls = _hold_orchestration(monkeypatch)
    usage = _spy_usage(monkeypatch)
    coalesced_before = _counter_total(metrics.ANALYZE_COALESCED)
    leader, follower = _run_two(gateway_client, alice_token, release)

    assert leader.status_code == follower.status_code == 200, (leader.text, follower.text)
    assert len(calls) == 1, "the identical request ran a second pipeline"
    lj, fj = leader.json(), follower.json()
    assert lj["drafts"] == fj["drafts"]
    # Each answers under its own id and gate outcomes.
    assert lj["request_id"] == "sf-leader" and fj["request_id"] == "sf-second"
    assert fj["policy_decisions"].get("coalesced") is True and fj["cost_meta"]["cache_hit"] is True
    assert "coalesced" not in lj["policy_decisions"] and lj["cost_meta"]["cache_hit"] is False
    assert "coalesced" in follower.headers["Server-Timing"]
    # Quota: the follower's reservation is released in full; only the leader is charged.
    zero_settlements = [k for a, k in usage if a == (0, 0, 0.0)]
    assert len(zero_settlements) == 1 and zero_settlements[0]["reserved_tokens"] > 0
    assert any(k.get("prompt_tokens") is not None for _, k in usage)
    # Invariant #4: one audit row each.
    models = {m for m, _ in _last_analyze_audit_rows(2)}
    assert "coalesced" in models and len(models) == 2
    assert _counter_total(metrics.ANALYZE_COALESCED) == coalesced_before + 1
    assert not gw_main._inflight_analyses


def test_different_inputs_are_not_merged(monkeypatch, gateway_client, alice_token, patched_ai_engine):
    release, calls = _hold_orchestration(monkeypatch)
    a, b = _run_two(gateway_client, alice_token, release, second_hint="argue claim 2", expect_flights=2)
    assert a.status_code == b.status_code == 200
    assert len(calls) == 2
    assert "coalesced" not in b.json()["policy_decisions"]


def test_a_leader_failure_is_the_followers_failure_with_its_quota_back(
    monkeypatch, gateway_client, alice_token, patched_ai_engine
):
    release, _ = _hold_orchestration(monkeypatch, fail_with=orch.AnalysisTimeout("simulated deadline"))
    usage = _spy_usage(monkeypatch)
    a, b = _run_two(gateway_client, alice_token, release)
    assert a.status_code == b.status_code == 504
    assert sum(1 for args, _ in usage if args == (0, 0, 0.0)) == 2
    assert all('"error": true' in pd for _, pd in _last_analyze_audit_rows(2))
    assert not gw_main._inflight_analyses


def _asgi_analyze(app, token: str, request_id: str, sink: list) -> asyncio.Task:
    """Drive the gateway app directly, so the request task can be cancelled
    natively (what uvicorn does to in-flight requests at shutdown)."""
    body = json.dumps(
        {"oa_text": _OA, "case_id": "CASE-2025-001", "target_patent_no": "US17123456"}
    ).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/oa/analyze",
        "raw_path": b"/v1/oa/analyze",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"authorization", f"Bearer {token}".encode()),
            (obs.REQUEST_ID_HEADER.lower().encode(), request_id.encode()),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)

    async def send(message):
        sink.append(message)

    return asyncio.create_task(app(scope, receive, send))


async def _until(pred, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < end, "condition never became true"
        await asyncio.sleep(0.01)


async def test_a_cancelled_leader_still_pays_for_the_analysis_its_follower_gets(
    monkeypatch, gateway_app, patched_ai_engine
):
    """W2-A2/B1: the leader refunded its reservation on cancellation and the
    follower refunded its own — the analysis the follower received was paid by
    nobody, repeatable at will (send twice, drop the first)."""
    from backend.gateway.auth import issue_token

    release = asyncio.Event()
    real = gw_main.orchestrate_analysis

    async def held(*args, **kwargs):
        await release.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(gw_main, "orchestrate_analysis", held)
    usage = _spy_usage(monkeypatch)
    analysed_before = _counter_total(metrics.OA_ANALYZED)
    token = issue_token("alice")

    leader_sink, follower_sink = [], []
    leader = _asgi_analyze(gateway_app, token, "sf-gone-leader", leader_sink)
    await _until(lambda: len(gw_main._inflight_analyses) == 1)
    flight = next(iter(gw_main._inflight_analyses.values()))
    follower = _asgi_analyze(gateway_app, token, "sf-gone-follower", follower_sink)
    await _until(lambda: flight.waiters == 2)
    leader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader
    release.set()
    await asyncio.wait_for(follower, 30)
    await _until(lambda: flight.task.done())

    status = next(m["status"] for m in follower_sink if m["type"] == "http.response.start")
    assert status == 200
    charged = [k for _, k in usage if k.get("prompt_tokens")]
    assert len(charged) == 1, f"the analysis was charged {len(charged)} times: {usage}"
    assert charged[0]["reserved_tokens"] > 0  # the leader's reservation, settled at true usage
    assert sum(1 for args, _ in usage if args == (0, 0, 0.0)) == 1  # only the follower's refund
    assert _counter_total(metrics.OA_ANALYZED) == analysed_before + 1
    rows = {m for m, _ in _last_analyze_audit_rows(2)}
    assert rows == {None, "coalesced"}  # the cancelled leader's error row + the follower's
    # The shared task also wrote the cache although its starter was gone.
    third_sink = []
    await asyncio.wait_for(_asgi_analyze(gateway_app, token, "sf-gone-third", third_sink), 30)
    third = json.loads(b"".join(m.get("body", b"") for m in third_sink if m["type"] == "http.response.body"))
    assert third["cost_meta"]["cache_hit"] is True


async def test_a_pipeline_cancelled_mid_draft_leaves_no_unread_task_error(monkeypatch, caplog, patched_ai_engine):
    """W2-A5: claim masking fails, one rejection fails fast, the other is
    cancelled while drafting — its element-comparison task had already failed
    and nobody read the exception."""
    from backend.shared.models import AnalysisRequest, User, UserRole

    real_call = orch.AIEngineClient.call
    drafts: list[int] = []

    async def call(self, path, payload):
        if path == "/v1/claim_tree":
            return {"claim_tree": [{"claim_no": 1, "text": "A widget comprising a gear.", "is_independent": True}]}
        if path == "/v1/draft_response":
            drafts.append(1)
            if len(drafts) == 1:
                await asyncio.sleep(5)  # the first rejection drafts slowly
        return await real_call(self, path, payload)

    real_redact = masking.redact

    def redact(text, tenant):
        if "widget" in text:
            raise RuntimeError("mapping store down")
        return real_redact(text, tenant)

    monkeypatch.setattr(orch.AIEngineClient, "call", call)
    monkeypatch.setattr(masking, "redact", redact)
    user = User(user_id="alice", tenant_id="tenant_a", role=UserRole.ATTORNEY, display_name="A")
    req = AnalysisRequest(oa_text=_OA, case_id="CASE-2025-001", target_patent_no="US17123456")
    with caplog.at_level(logging.ERROR, logger="asyncio"):
        with pytest.raises(RuntimeError, match="mapping store down"):
            await orch.orchestrate_analysis(user, req)
        await asyncio.sleep(0.1)
        gc.collect()
        await asyncio.sleep(0.1)
    assert len(drafts) >= 2, "the scenario needs two rejections"
    leaked = [r.getMessage() for r in caplog.records if "never retrieved" in r.getMessage()]
    assert not leaked, leaked


async def test_a_flight_cancelled_before_it_starts_releases_the_reservation(monkeypatch):
    """asyncio.run cancels every task at shutdown; a task cancelled before its
    first step never runs its body, so _run_and_settle's own release never
    ran and the starter's reservation leaked (review W2-C4)."""
    from backend.shared.models import AnalysisRequest, User, UserRole

    released = []
    monkeypatch.setattr(rate_limit, "record_usage", lambda user, *a, **k: released.append((a, k)))
    user = User(user_id="alice", tenant_id="tenant_a", role=UserRole.ATTORNEY, display_name="A")
    body = AnalysisRequest(oa_text=_OA, case_id="CASE-2025-001", target_patent_no="US17123456")
    progress = {"started": False}

    def release_if_never_started():
        if not progress["started"]:
            gw_main._release_reservation(user, 77)

    flight = gw_main._start_flight(
        None,
        gw_main._run_and_settle(
            user,
            body,
            circuit_open=False,
            pre_redacted=("x", []),
            pre_redacted_hint=None,
            cache_key=None,
            reserved_tokens=77,
            progress=progress,
        ),
        on_cancelled=release_if_never_started,
    )
    flight.task.cancel()  # before its first step
    with pytest.raises(asyncio.CancelledError):
        await flight.task
    await asyncio.sleep(0)  # done callbacks
    assert progress["started"] is False
    assert released == [((0, 0, 0.0), {"reserved_tokens": 77})]


def test_a_failed_cache_write_does_not_fail_a_paid_analysis(monkeypatch, gateway_client, alice_token, patched_ai_engine):
    """It now runs in the shared task, so a failure would fail the leader AND
    every follower — after the analysis was charged (review W2-C8)."""

    def broken(*args, **kwargs):
        raise RuntimeError("cache backend exploded")

    monkeypatch.setattr(cache_mod, "set_response_at", broken)
    resp = _analyze(gateway_client, alice_token)
    assert resp.status_code == 200, resp.text


async def test_one_waiter_leaving_does_not_cancel_the_shared_analysis():
    gate = asyncio.Event()

    async def work():
        await gate.wait()
        return "result"

    flight = gw_main._start_flight("k-shared", work())
    a = asyncio.create_task(gw_main._await_flight(flight))
    b = asyncio.create_task(gw_main._await_flight(flight))
    await asyncio.sleep(0)
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    assert not flight.task.cancelled()
    gate.set()
    assert await b == "result"
    await asyncio.sleep(0)  # done callback
    assert "k-shared" not in gw_main._inflight_analyses


async def test_the_analysis_stops_when_every_waiter_has_gone():
    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.sleep(30)

    flight = gw_main._start_flight("k-abandoned", work())
    waiter = asyncio.create_task(gw_main._await_flight(flight))
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert gw_main._joinable_flight("k-abandoned") is None  # being cancelled: not joinable
    for _ in range(10):
        if flight.task.cancelled() and "k-abandoned" not in gw_main._inflight_analyses:
            break
        await asyncio.sleep(0)
    assert flight.task.cancelled()
    assert "k-abandoned" not in gw_main._inflight_analyses


# ---------------------------------------------------------------------------
# BE-6: the audit row survives a cancelled handler
# ---------------------------------------------------------------------------
def _audit_finally_handler():
    async def handler():
        try:
            await asyncio.sleep(30)
        finally:
            await gw_main._submit(gw_main._safe_audit_write, endpoint="/v1/oa/analyze")

    return handler


@pytest.mark.parametrize("busy", [False, True])
async def test_an_anyio_cancelled_handler_still_writes_its_audit_row(monkeypatch, busy):
    """W2-A1: anyio re-cancels at every await of a cancelled scope. The first
    version awaited an unshielded executor future — cancelling it cancelled
    the queued job, and 28 of 30 rows were lost (5 of 5 with busy workers).
    ``busy``: the only worker is occupied, so every write is still queued
    when the cancel lands."""
    from concurrent.futures import ThreadPoolExecutor

    import anyio

    written = []
    monkeypatch.setattr(gw_main, "_safe_audit_write", lambda **kw: written.append(1))
    loop = asyncio.get_running_loop()
    gate = threading.Event()
    blockers = []
    if busy:
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        blockers.append(loop.run_in_executor(None, gate.wait, 5))
    rounds = 20
    try:
        for _ in range(rounds):
            async with anyio.create_task_group() as tg:
                tg.start_soon(_audit_finally_handler())
                await asyncio.sleep(0.01)
                tg.cancel_scope.cancel()  # what BaseHTTPMiddleware's task group does
    finally:
        gate.set()
        await asyncio.gather(*blockers)
    deadline = time.monotonic() + 5
    while len(written) < rounds and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert len(written) == rounds, f"dropped {rounds - len(written)} of {rounds} audit rows"


async def test_a_natively_cancelled_handler_still_writes_its_audit_row(monkeypatch):
    """uvicorn cancels request tasks at shutdown. The write must survive a
    second cancel that lands while it is still QUEUED — the first version of
    this test let a fresh pool start the job before the second cancel, and
    passed with the unshielded code too (review W2-C2). One worker, kept busy,
    makes the queued state certain."""
    from concurrent.futures import ThreadPoolExecutor

    written = threading.Event()
    monkeypatch.setattr(gw_main, "_safe_audit_write", lambda **kw: written.set())
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    gate = threading.Event()
    blocker = loop.run_in_executor(None, gate.wait, 5)  # occupies the only worker
    task = asyncio.create_task(_audit_finally_handler()())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)  # the finally submits the write (queued) and awaits it …
    task.cancel()  # … and is cancelled again while the job is still queued
    with pytest.raises(asyncio.CancelledError):
        await task
    gate.set()
    await blocker
    assert await asyncio.to_thread(written.wait, 2.0), "the audit row was dropped with the cancelled request"


async def test_a_reservation_made_after_cancellation_is_given_back(monkeypatch):
    """The thread finishes the reservation even if the request was cancelled
    meanwhile — it must be released, not left reserved until the bucket
    expires."""
    released = threading.Event()
    seen = {}

    def slow_reserve(user, tokens, decisions):
        time.sleep(0.2)
        return 321

    def record_usage(user, *args, **kwargs):
        seen.update(args=args, kwargs=kwargs)
        released.set()

    monkeypatch.setattr(rate_limit, "reserve_llm_budget", slow_reserve)
    monkeypatch.setattr(rate_limit, "record_usage", record_usage)
    task = asyncio.create_task(gw_main._reserve(object(), 1000, {}))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(released.wait, 3.0)
    assert seen["args"] == (0, 0, 0.0) and seen["kwargs"]["reserved_tokens"] == 321


# ---------------------------------------------------------------------------
# M-13: audit reads have their own read-only connection
# ---------------------------------------------------------------------------
def _write_row(writer, i: int) -> None:
    from backend.shared.models import User, UserRole

    writer.write(
        user=User(user_id="alice", tenant_id="tenant_a", role=UserRole.ATTORNEY, display_name="alice"),
        case_id=f"case-{i}",
        endpoint="/v1/oa/analyze",
        request_payload={"q": i},
        response_payload={"a": i},
        masked_rules=[],
        model_used="mock",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1,
        policy_decisions={},
    )


def test_a_restore_is_not_undone_by_a_crashed_instances_wal(tmp_path, monkeypatch):
    """W2-C1: the audit db runs in WAL mode. A crashed gateway leaves
    audit.db-wal next to the db; restoring a backup into that folder and
    restarting let SQLite replay the stale WAL over the restored file — 5
    backed-up rows came back as 12, and restore() reported ok."""
    import shutil

    from backend.gateway import backup
    from backend.shared import config

    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setattr(config, "AUDIT_DB_PATH", live / "audit.db")
    monkeypatch.setattr(config, "MAPPING_DB_PATH", live / "mapping.db")
    monkeypatch.setattr(config, "PATENT_DB_PATH", live / "patent.db")
    monkeypatch.setattr(config, "AUDIT_ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    writer = audit.AuditWriter(path=live / "audit.db")
    for i in range(5):
        _write_row(writer, i)
    snap = backup.snapshot()
    for i in range(5, 12):
        _write_row(writer, i)
    # "Crash": the data folder as a killed process leaves it — db + live WAL.
    crashed = tmp_path / "crashed"
    crashed.mkdir()
    for name in ("audit.db", "audit.db-wal", "audit.db-shm"):
        if (live / name).exists():
            shutil.copy2(live / name, crashed / name)
    writer.close()
    assert (crashed / "audit.db-wal").exists(), "the scenario needs a stale WAL"

    result = backup.restore(snap["backup_id"], crashed)
    assert result["ok"]
    assert "audit.db-wal" in result["removed_journals"]
    conn = sqlite3.connect(crashed / "audit.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 5
    finally:
        conn.close()


def test_audit_reads_are_read_only(tmp_path):
    writer = audit.AuditWriter(path=tmp_path / "audit.db")
    try:
        with pytest.raises(sqlite3.OperationalError):
            writer._read_conn.execute("CREATE TABLE intruder(a)")
        writer.ping()
    finally:
        writer.close()


def test_an_open_audit_read_does_not_hold_up_audit_writes(tmp_path):
    """W2-A3: with the separate read connection and a rollback journal, an
    in-progress read (a chain verify) made every audit COMMIT wait for it —
    3 s of read, 3.05 s of write. WAL lets them run side by side."""
    writer = audit.AuditWriter(path=tmp_path / "audit.db")
    try:
        assert writer._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        for i in range(5):
            _write_row(writer, i)
        cursor = writer._read_conn.execute("SELECT * FROM audit")
        cursor.fetchone()  # the read is now open, holding its snapshot
        started = time.monotonic()
        _write_row(writer, 99)
        assert time.monotonic() - started < 1.0, "the audit write waited for a reader"
        cursor.fetchall()
        assert writer._fetchall("SELECT COUNT(*) FROM audit")[0][0] == 6
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# BE-12: Redis waits are bounded
# ---------------------------------------------------------------------------
def test_the_quota_redis_client_has_timeouts(monkeypatch):
    import redis

    captured = {}

    def fake_from_url(url, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(rate_limit, "_REDIS_CLIENT", None)
    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(fake_from_url))
    assert rate_limit._quota_redis() is not None
    assert captured["socket_timeout"] == settings.REDIS_SOCKET_TIMEOUT_SEC
    assert captured["socket_connect_timeout"] == settings.REDIS_SOCKET_TIMEOUT_SEC


# ---------------------------------------------------------------------------
# OBS-9 / BE-13: liveness, readiness, warm-up
# ---------------------------------------------------------------------------
def _fake_get(status_code: int):
    def get(url, **kwargs):
        return httpx.Response(status_code, request=httpx.Request("GET", url))

    return get


class _ExplodingProbe:
    def check(self):
        raise AssertionError("liveness ran a readiness check")


def test_liveness_touches_nothing(monkeypatch, gateway_client, ai_engine_app):
    from backend.ai_engine import main as ai_main

    # Replace the probe objects themselves (the first version patched the
    # check factory, which the probe had already captured — W2 test review).
    monkeypatch.setattr(gw_main, "_READINESS", _ExplodingProbe())
    monkeypatch.setattr(ai_main, "_READINESS", _ExplodingProbe())
    resp = gateway_client.get("/livez")
    assert resp.status_code == 200 and resp.json() == {"ok": True}
    with TestClient(ai_engine_app) as engine:
        assert engine.get("/livez").json() == {"ok": True}


def test_liveness_needs_no_worker_thread():
    """A sync handler waits for a free threadpool worker; the AI Engine's
    sync inference endpoints hold them for minutes (W2-B2)."""
    from backend.ai_engine import main as ai_main

    for handler in (gw_main.livez, gw_main.readyz, ai_main.livez, ai_main.readyz):
        assert inspect.iscoroutinefunction(handler), handler


def test_gateway_readiness_says_only_ok_or_not(monkeypatch, gateway_client):
    probe = readiness.ReadinessProbe(gw_main._readiness_checks)
    monkeypatch.setattr(gw_main, "_READINESS", probe)
    monkeypatch.setattr(gw_main.httpx, "get", _fake_get(200))  # the AI Engine's /readyz
    ok = gateway_client.get("/readyz")
    assert ok.status_code == 200 and ok.json() == {"ok": True}

    monkeypatch.setattr(gw_main.httpx, "get", _fake_get(503))
    probe.reset()
    down = gateway_client.get("/readyz")
    assert down.status_code == 503 and down.json() == {"ok": False}  # no dependency names
    rendered = "\n".join(metrics.DEPENDENCY_UP.render())
    assert 'dependency_up{dependency="ai_engine"} 0' in rendered
    assert 'dependency_up{dependency="audit_db"} 1' in rendered


async def test_readiness_checks_run_on_their_own_threads():
    """Not the request threadpool and not the default executor that carries
    the gateway's audit writes and quota settlements (review W2-C7)."""
    seen = []
    probe = readiness.ReadinessProbe(lambda: {"dep": lambda: seen.append(threading.current_thread().name)})
    ready, _ = await probe.check_async()
    assert ready and seen[0].startswith("readiness")


def test_readiness_is_evaluated_at_most_once_per_ttl():
    runs = []
    probe = readiness.ReadinessProbe(lambda: {"dep": lambda: runs.append(1)}, ttl_sec=60)
    assert probe.check()[0] and probe.check()[0]
    assert len(runs) == 1


def test_engine_liveness_and_readiness_need_no_internal_token(monkeypatch, ai_engine_app):
    from backend.ai_engine import main as ai_main

    monkeypatch.setattr(settings, "LLM_MODE", "dify")  # non-mock: other paths need the token
    monkeypatch.setattr(settings, "INTERNAL_TOKEN", "")
    monkeypatch.setattr(ai_main, "_READINESS", readiness.ReadinessProbe(ai_main._readiness_checks))
    with TestClient(ai_engine_app) as client:
        assert client.get("/livez").json() == {"ok": True}
        assert client.get("/readyz").status_code == 200
        assert client.post("/v1/deadline", json={}).status_code == 401


@pytest.fixture()
def fresh_warmup(monkeypatch):
    """Warm-up state is per process; give the test its own (W2 test review:
    whichever test first started the engine decided it for the session)."""
    from backend.ai_engine import warmup

    monkeypatch.setattr(warmup, "_done", threading.Event())
    monkeypatch.setattr(warmup, "_started", False)
    return warmup


def test_engine_is_not_ready_until_the_real_warm_up_finished(monkeypatch, fresh_warmup, ai_engine_app):
    from backend.ai_engine import main as ai_main

    release = threading.Event()

    def slow_preload(url, **kwargs):  # Ollama loading the model
        release.wait(10)
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(settings, "LLM_MODE", "local")
    monkeypatch.setattr(fresh_warmup.httpx, "post", slow_preload)
    monkeypatch.setattr(ai_main.httpx, "get", _fake_get(200))  # Ollama itself answers
    probe = readiness.ReadinessProbe(ai_main._readiness_checks, ttl_sec=0)
    monkeypatch.setattr(ai_main, "_READINESS", probe)
    try:
        with TestClient(ai_engine_app) as client:  # lifespan starts the warm-up
            warming = client.get("/readyz")
            release.set()
            assert _wait_until(fresh_warmup.is_done)
            warm = client.get("/readyz")
    finally:
        release.set()
    assert warming.status_code == 503 and warming.json() == {"ok": False}
    assert warm.status_code == 200 and warm.json() == {"ok": True}


def test_warm_up_loads_the_llm_before_the_embedding_models(monkeypatch, fresh_warmup):
    """The embedder / reranker take the GPU only if enough VRAM is free when
    they load; loading them first could starve the LLM (W2-B5)."""
    from backend.ai_engine import rag

    monkeypatch.setattr(settings, "LLM_MODE", "local")
    monkeypatch.setattr(rag._embedder, "backend", "qwen3")
    monkeypatch.setattr(rag._reranker, "backend", "qwen3-4b")
    assert [name for name, _ in fresh_warmup._steps()] == ["ollama", "embedder", "reranker"]


def test_a_model_is_loaded_once_when_warm_up_and_a_request_race(monkeypatch):
    """W2-B3: the start-up warm-up and the first request each loaded the 4B
    embedder — two copies on the 8 GB card."""
    from backend.ai_engine import rag

    loads = []

    class _Model:
        def get_sentence_embedding_dimension(self):
            return 8

    def slow_build():
        loads.append(threading.current_thread().name)
        time.sleep(0.2)
        return _Model()

    emb = rag.Embedder(backend="mock")
    emb.backend = "qwen3"
    monkeypatch.setattr(emb, "_build_st", slow_build)
    threads = [threading.Thread(target=lambda: emb.dim, name=f"t{i}") for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(loads) == 1 and emb.dim == 8


def test_the_reranker_is_loaded_once_and_published_complete(monkeypatch):
    """Same race for the reranker; and score() reads _model without the
    lock, so _model must be set only after the tokenizer ids and prompt
    parts (review W2-B3; the lock had no test — W2-C)."""
    import sys
    import types

    from backend.ai_engine import rag

    loads = []

    class _Tok:
        def convert_tokens_to_ids(self, token):
            return 1 if token == "yes" else 0

    class _Model:
        def to(self, device):
            return self

        def eval(self):
            return self

    class _AutoTokenizer:
        @staticmethod
        def from_pretrained(name, **kwargs):
            return _Tok()

    class _AutoModel:
        @staticmethod
        def from_pretrained(name, **kwargs):
            loads.append(name)
            time.sleep(0.2)
            return _Model()

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(float16="f16", float32="f32"))
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        types.SimpleNamespace(AutoTokenizer=_AutoTokenizer, AutoModelForCausalLM=_AutoModel),
    )
    monkeypatch.setattr(rag, "pick_device", lambda preference, need_gb: "cpu")
    reranker = rag.Reranker(backend="qwen3-4b")
    seen_incomplete = []

    def use():
        reranker.ensure_loaded()
        if not hasattr(reranker, "_suffix") or not hasattr(reranker, "_yes"):
            seen_incomplete.append(1)

    threads = [threading.Thread(target=use) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(loads) == 1
    assert not seen_incomplete


def test_token_checks_against_a_redis_revocation_store_leave_the_event_loop(
    monkeypatch, gateway_client, alice_token
):
    """With REVOCATION_BACKEND=redis every authenticated request did a Redis
    round trip on the event loop (review W2-C, research 09 BE-6)."""
    from backend.gateway import auth

    on_loop = []
    real = auth.verify_token

    def spy(token):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return real(token)

    monkeypatch.setattr(auth, "verify_token", spy)
    monkeypatch.setattr(settings, "REVOCATION_BACKEND", "redis")
    resp = gateway_client.get("/v1/quota", headers={"Authorization": f"Bearer {alice_token}"})
    assert resp.status_code == 200, resp.text
    assert on_loop == [False]


def test_local_mode_warm_up_preloads_the_model(monkeypatch):
    from backend.ai_engine import warmup

    posted = []

    def fake_post(url, **kwargs):
        posted.append((url, kwargs["json"]))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(settings, "LLM_MODE", "local")
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://ollama.test:11434/v1")
    monkeypatch.setattr(warmup, "_done", threading.Event())
    monkeypatch.setattr(warmup.httpx, "post", fake_post)
    assert warmup.needed() and not warmup.is_done()
    warmup.run()
    assert warmup.is_done()
    url, body = posted[0]
    assert url == "http://ollama.test:11434/api/generate"
    assert body == {"model": settings.LLM_MODEL_LOCAL, "keep_alive": settings.OLLAMA_KEEP_ALIVE}


def test_a_failed_warm_up_step_never_blocks_readiness_for_good(monkeypatch):
    from backend.ai_engine import warmup

    def down(url, **kwargs):
        raise httpx.ConnectError("ollama down")

    monkeypatch.setattr(settings, "LLM_MODE", "local")
    monkeypatch.setattr(warmup, "_done", threading.Event())
    monkeypatch.setattr(warmup.httpx, "post", down)
    warmup.run()  # logs, does not raise
    assert warmup.is_done()
