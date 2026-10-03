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
import gc
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


def test_a_nonsense_deadline_header_is_ignored():
    now = time.time()
    assert time_budget.parse_deadline("garbage", now=now) is None
    assert time_budget.parse_deadline(str(now + 7200), now=now) is None
    assert time_budget.parse_deadline(str(now - 600), now=now) is None
    assert time_budget.parse_deadline(str(now + 100), now=now) == pytest.approx(now + 100)


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
async def test_a_cancelled_handler_still_writes_its_audit_row(monkeypatch):
    written = threading.Event()

    def slow_write(**kwargs):
        time.sleep(0.2)
        written.set()

    monkeypatch.setattr(gw_main, "_safe_audit_write", slow_write)

    async def handler():
        try:
            await asyncio.sleep(30)
        finally:
            await gw_main._audit_off_loop(endpoint="/v1/oa/analyze")

    task = asyncio.create_task(handler())
    await asyncio.sleep(0)
    task.cancel()  # client gone …
    await asyncio.sleep(0)
    task.cancel()  # … and cancelled again inside the finally (anyio is level-triggered)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert written.wait(2.0), "the audit row was dropped with the cancelled request"


# ---------------------------------------------------------------------------
# M-13: audit reads have their own read-only connection
# ---------------------------------------------------------------------------
def test_audit_reads_are_read_only_and_do_not_queue_behind_writes(tmp_path):
    writer = audit.AuditWriter(path=tmp_path / "audit.db")
    try:
        with pytest.raises(sqlite3.OperationalError):
            writer._read_conn.execute("CREATE TABLE intruder(a)")
        holding, release = threading.Event(), threading.Event()

        def hold_write_lock():
            with writer._lock:
                holding.set()
                release.wait(5)

        t = threading.Thread(target=hold_write_lock)
        t.start()
        assert holding.wait(2)
        started = time.monotonic()
        writer._fetchall("SELECT COUNT(*) FROM audit")
        assert time.monotonic() - started < 1.0
        release.set()
        t.join()
        writer.ping()
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


def test_gateway_liveness_touches_nothing(monkeypatch, gateway_client):
    monkeypatch.setattr(gw_main, "_readiness_checks", lambda: pytest.fail("liveness ran a check"))
    resp = gateway_client.get("/livez")
    assert resp.status_code == 200 and resp.json() == {"ok": True}


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


def test_engine_is_not_ready_until_warm_up_finished(monkeypatch, ai_engine_app):
    from backend.ai_engine import main as ai_main
    from backend.ai_engine import warmup

    monkeypatch.setattr(warmup, "start_background", lambda: None)
    monkeypatch.setattr(warmup, "is_done", lambda: False)
    monkeypatch.setattr(ai_main, "_READINESS", readiness.ReadinessProbe(ai_main._readiness_checks))
    with TestClient(ai_engine_app) as client:
        resp = client.get("/readyz")
    assert resp.status_code == 503 and resp.json() == {"ok": False}


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
