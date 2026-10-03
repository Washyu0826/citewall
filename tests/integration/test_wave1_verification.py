"""End-to-end checks for the optimisation wave-1 fixes, written after an
adversarial review found what the unit tests did not cover (FAILURE_LOG
B-22 … B-27). Everything runs through the real gateway and the in-process
AI Engine (mock LLM).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.gateway import cache as cache_mod
from backend.shared import metrics
from backend.shared import observability as obs
from backend.shared.config import settings

_OA = (Path(__file__).resolve().parents[2] / "data" / "oa_samples" / "sample_oa_us.txt").read_text(
    encoding="utf-8"
)


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(cache_mod, "_cache", cache_mod._MemoryCache())


def _analyze(client, token, *, request_id=None, case_id="CASE-2025-001"):
    headers = {"Authorization": f"Bearer {token}"}
    if request_id:
        headers[obs.REQUEST_ID_HEADER] = request_id
    return client.post(
        "/v1/oa/analyze",
        headers=headers,
        json={"oa_text": _OA, "case_id": case_id, "target_patent_no": "US17123456"},
    )


# ---------------------------------------------------------------------------
# Request id (B-14 → regression B-22)
# ---------------------------------------------------------------------------
def test_response_request_id_is_the_logged_request_id(
    gateway_client, alice_token, patched_ai_engine
):
    resp = _analyze(gateway_client, alice_token, request_id="trace-wave1-a")
    assert resp.status_code == 200, resp.text
    assert resp.headers[obs.REQUEST_ID_HEADER] == "trace-wave1-a"
    assert resp.json()["request_id"] == "trace-wave1-a"


def test_an_overlong_client_request_id_never_breaks_an_analysis(
    gateway_client, alice_token, patched_ai_engine
):
    """B-22: a 129–200 char X-Request-ID used to fail AnalysisResponse
    validation AFTER all model work — a 500 with the quota refunded."""
    resp = _analyze(gateway_client, alice_token, request_id="x" * 300)
    assert resp.status_code == 200, resp.text
    rid = resp.json()["request_id"]
    assert len(rid) <= 128
    assert rid == resp.headers[obs.REQUEST_ID_HEADER]


def test_a_cache_hit_reports_the_hitting_requests_id(
    gateway_client, alice_token, patched_ai_engine
):
    first = _analyze(gateway_client, alice_token, request_id="trace-first")
    second = _analyze(gateway_client, alice_token, request_id="trace-second")
    assert first.status_code == second.status_code == 200
    assert second.json()["cost_meta"]["cache_hit"] is True
    assert second.json()["request_id"] == "trace-second"


# ---------------------------------------------------------------------------
# Degraded results are never cached (B-15 → B-24)
# ---------------------------------------------------------------------------
def test_a_result_with_a_failed_retrieval_is_not_cached(
    monkeypatch, gateway_client, alice_token, patched_ai_engine
):
    """A Qdrant blip leaves drafts without a grounded set. That result is
    shown but must not be served from cache to the attorney's retry."""
    from backend.ai_engine import rag

    real_retrieve = rag.retrieve
    state = {"fail": True}

    def flaky_retrieve(*args, **kwargs):
        if state["fail"]:
            raise RuntimeError("vector store blip")
        return real_retrieve(*args, **kwargs)

    monkeypatch.setattr(rag, "retrieve", flaky_retrieve)
    first = _analyze(gateway_client, alice_token)
    assert first.status_code == 200, first.text

    state["fail"] = False
    second = _analyze(gateway_client, alice_token)
    assert second.status_code == 200
    assert second.json()["cost_meta"]["cache_hit"] is False


def test_a_clean_result_is_cached(gateway_client, alice_token, patched_ai_engine):
    first = _analyze(gateway_client, alice_token)
    second = _analyze(gateway_client, alice_token)
    assert first.json()["cost_meta"]["cache_hit"] is False
    assert second.json()["cost_meta"]["cache_hit"] is True


# ---------------------------------------------------------------------------
# Case ids never in URLs — enforced server-side (B-10 → B-27)
# ---------------------------------------------------------------------------
def test_a_case_id_in_the_query_string_is_refused(gateway_client, alice_token):
    resp = gateway_client.get(
        "/v1/quota?case_id=CASE-2025-001", headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert resp.status_code == 400
    assert "X-Case-Id" in resp.json()["detail"]
    # Without it the same call works.
    ok = gateway_client.get("/v1/quota", headers={"Authorization": f"Bearer {alice_token}"})
    assert ok.status_code == 200


# ---------------------------------------------------------------------------
# An unhandled 500 still carries the reference id (V-F7)
# ---------------------------------------------------------------------------
def test_an_unhandled_error_answers_with_the_request_id(monkeypatch, gateway_app, alice_token):
    from backend.gateway import main as gw_main

    async def crash(*args, **kwargs):
        raise RuntimeError("simulated orchestrator crash")

    monkeypatch.setattr(gw_main, "orchestrate_analysis", crash)
    with TestClient(gateway_app, raise_server_exceptions=False) as client:
        resp = _analyze(client, alice_token, request_id="trace-crash-1")
    assert resp.status_code == 500
    assert resp.headers.get(obs.REQUEST_ID_HEADER) == "trace-crash-1"


# ---------------------------------------------------------------------------
# A failed inference endpoint counts as an LLM error (B-18 → B-23)
# ---------------------------------------------------------------------------
def test_a_failed_inference_call_counts_as_an_llm_error(monkeypatch, ai_engine_app):
    from backend.ai_engine import oa_analyzer

    def boom(*args, **kwargs):
        raise RuntimeError("model provider down")

    monkeypatch.setattr(oa_analyzer, "parse_oa", boom)
    before = sum(v for _, v in metrics.LLM_ERRORS._snapshot())
    headers = {"x-internal-token": settings.INTERNAL_TOKEN} if settings.INTERNAL_TOKEN else {}
    with TestClient(ai_engine_app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/v1/parse_oa",
            headers=headers,
            json={
                "oa_text": "Claims 1-3 are rejected.",
                "tenant_id": "tenant_a",
                "case_id": "CASE-2025-001",
                "target_patent_no": "US17123456",
                "security_level": "public",
            },
        )
    assert resp.status_code == 500
    after = sum(v for _, v in metrics.LLM_ERRORS._snapshot())
    assert after == before + 1
