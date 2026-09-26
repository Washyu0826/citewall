"""UX_REVIEW T1 — the analyze RESPONSE carries the real per-request gate
outcomes (`AnalysisResponse.policy_decisions`).

Before this, the SPA's trust chips were hard-coded constants — a fake trust
signal on a product whose pitch is verifiable trust. The contract pinned here:

  * Success path: the response ships the same decisions dict the audit row
    records (authz / rate-limit / quota all True, circuit_open False).
  * Cache hit: the response reflects THIS request's gate outcomes — auth,
    RPM and quota all re-ran; only the LLM work was skipped. A cached copy
    must never replay the ORIGINAL run's decisions.
"""

from __future__ import annotations

_CASE = "CASE-2025-001"  # alice has ACL


def _analyze(client, token, oa_text: str):
    resp = client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"oa_text": oa_text, "case_id": _CASE, "target_patent_no": "US17000052"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_success_response_carries_real_policy_decisions(
    gateway_client, alice_token, patched_ai_engine
):
    body = _analyze(gateway_client, alice_token, "Policy-decisions response contract test.")
    pd = body.get("policy_decisions")
    assert isinstance(pd, dict) and pd, body.keys()
    assert pd.get("authn_passed") is True
    assert pd.get("authz_passed") is True
    assert pd.get("rate_limit_passed") is True
    assert pd.get("quota_passed") is True
    assert pd.get("circuit_open") is False


def test_cache_hit_response_reflects_current_request_gates(
    gateway_client, alice_token, patched_ai_engine
):
    oa = "Policy-decisions cache-hit contract test — identical across calls."
    first = _analyze(gateway_client, alice_token, oa)
    assert first["cost_meta"]["cache_hit"] is False

    second = _analyze(gateway_client, alice_token, oa)
    assert second["cost_meta"]["cache_hit"] is True
    pd = second.get("policy_decisions")
    # The hit's gates re-ran for THIS request — all True again, and present
    # even though the cached payload was serialised before the field existed
    # in it (the gateway overwrites on every return path).
    assert isinstance(pd, dict) and pd
    assert pd.get("authz_passed") is True
    assert pd.get("rate_limit_passed") is True
    assert pd.get("quota_passed") is True
