"""Bounds on the endpoints a public demo visitor can reach (FAILURE_LOG B-52).

The phase-5 review found that a single anonymous visitor of the public demo
could stall the gateway for everyone: the redaction preview had no rate limit
and accepted 5 MB of text (masking grows faster than linearly), the audit
append accepted unbounded lists / dicts / integers, and /v1/audit/recent
returned every row for a negative limit. These hold for every deployment, not
only the demo.
"""

from __future__ import annotations

import pytest

from backend.shared import config

_ALICE_CASE = "CASE-2025-001"  # Alice has ACL for this case (see auth._CASE_ACL)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Case-Id": _ALICE_CASE}


def _login(client, user_id: str) -> str:
    resp = client.post("/v1/auth/login", json={"user_id": user_id, "password": f"demo-{user_id}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# Redaction preview: the analysis's own gates (RPM, then the size hard cap).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/v1/redact", "/v1/debug/redaction_preview"])
def test_redaction_over_the_analysis_hard_cap_is_refused(gateway_client, alice_token, path):
    too_long = "a" * (config.settings.REQUEST_HARD_LIMIT_TOKENS * 3 + 3)
    resp = gateway_client.post(path, headers=_headers(alice_token), json={"text": too_long})
    assert resp.status_code == 413, resp.text
    ok = gateway_client.post(path, headers=_headers(alice_token), json={"text": "a" * 1000})
    assert ok.status_code == 200, ok.text


def test_redaction_is_rate_limited(gateway_client, alice_token, monkeypatch):
    monkeypatch.setattr(config.settings, "DEFAULT_RPM", 2)
    codes = [
        gateway_client.post(
            "/v1/redact", headers=_headers(alice_token), json={"text": "hi"}
        ).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429], codes


# ---------------------------------------------------------------------------
# Audit append: every field bounded, and rate limited.
# ---------------------------------------------------------------------------
_APPEND_OK = {"case_id": _ALICE_CASE, "endpoint": "/v1/oa/analyze"}


@pytest.mark.parametrize(
    "extra",
    [
        {"masked_field_rules": ["r"] * 65},
        {"masked_field_rules": ["r" * 129]},
        {"policy_decisions": {f"k{i}": True for i in range(65)}},
        {"policy_decisions": {"k" * 65: True}},
        {"prompt_tokens": 10**20},
        {"completion_tokens": -1},
        {"latency_ms": 86_400_001},
    ],
    ids=[
        "rules-count",
        "rule-length",
        "decisions-count",
        "decision-key",
        "tokens-huge",
        "tokens-negative",
        "latency",
    ],
)
def test_audit_append_refuses_unbounded_fields(gateway_client, alice_token, extra):
    resp = gateway_client.post(
        "/v1/audit/append", headers=_headers(alice_token), json={**_APPEND_OK, **extra}
    )
    assert resp.status_code == 422, resp.text


def test_audit_append_accepts_values_within_bounds(gateway_client, alice_token):
    body = {
        **_APPEND_OK,
        "masked_field_rules": ["r" * 128] * 64,
        "policy_decisions": {f"k{i}": True for i in range(64)},
        "prompt_tokens": 10_000_000,
        "latency_ms": 86_400_000,
    }
    resp = gateway_client.post("/v1/audit/append", headers=_headers(alice_token), json=body)
    assert resp.status_code == 200, resp.text


def test_audit_append_is_rate_limited(gateway_client, alice_token, monkeypatch):
    monkeypatch.setattr(config.settings, "DEFAULT_RPM", 2)
    codes = [
        gateway_client.post(
            "/v1/audit/append", headers=_headers(alice_token), json=_APPEND_OK
        ).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429], codes


# ---------------------------------------------------------------------------
# Audit recent: the limit is clamped to 1..1000.
# ---------------------------------------------------------------------------
def test_audit_recent_clamps_the_limit(gateway_client, alice_token, monkeypatch):
    dave = _login(gateway_client, "audit_dave")
    for _ in range(3):  # a few rows in tenant_a
        gateway_client.post("/v1/redact", headers=_headers(alice_token), json={"text": "hi"})
    seen = {}

    def spy(tenant_id, limit):
        seen["limit"] = limit
        return []

    from backend.gateway import audit

    monkeypatch.setattr(audit.writer, "list_for_tenant", spy)
    for asked, expected in [(-1, 1), (0, 1), (50, 50), (10**9, 1000)]:
        resp = gateway_client.get(
            f"/v1/audit/recent?limit={asked}", headers={"Authorization": f"Bearer {dave}"}
        )
        assert resp.status_code == 200, resp.text
        assert seen["limit"] == expected, (asked, seen)
