"""GET /v1/cases — the dashboard / case-list endpoint.

Locks in: ACL-scoped visibility (same table as authorize_case_access), the
server-resolved security level, analysis metadata that never carries OA text,
and one audit row per call — including a role-denied call.
"""

from __future__ import annotations

import json

from backend.gateway import audit

_OA_MARKER = "UNIQUE-OA-MARKER-7F3A 請求項 9 之該第一電動車缺先行詞"


def _login(client, user_id: str) -> str:
    resp = client.post("/v1/auth/login", json={"user_id": user_id, "password": f"demo-{user_id}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _cases(client, token):
    return client.get("/v1/cases", headers={"Authorization": f"Bearer {token}"})


def test_attorney_sees_exactly_her_acl_cases(gateway_client, alice_token):
    resp = _cases(gateway_client, alice_token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = [c["case_id"] for c in body["cases"]]
    assert ids == ["CASE-2025-001", "CASE-2025-002", "CASE-2025-003"]
    assert body["read_only"] is False
    # Security level is the registry's answer, not a guess from the id.
    assert {c["security_level"] for c in body["cases"]} == {"public"}


def test_paralegal_list_is_narrower(gateway_client):
    token = _login(gateway_client, "bob")
    ids = [c["case_id"] for c in _cases(gateway_client, token).json()["cases"]]
    assert ids == ["CASE-2025-001", "CASE-2025-002"]


def test_analysis_metadata_appears_without_oa_text(gateway_client, alice_token, patched_ai_engine):
    oa_text = (
        "經濟部智慧財產局 審查意見通知函\n中華民國 114 年 5 月 29 日\n"
        f"{_OA_MARKER}，不符專利法第26條第2項之規定。"
    )
    r = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"oa_text": oa_text, "case_id": "CASE-2025-002", "target_patent_no": "TW202617461"},
    )
    assert r.status_code == 200, r.text

    body = _cases(gateway_client, alice_token).json()
    case = next(c for c in body["cases"] if c["case_id"] == "CASE-2025-002")
    summary = case["last_analysis"]
    assert summary is not None
    assert summary["analyzed_by"] == "alice"
    assert summary["jurisdiction"] == "TW"
    assert summary["rejection_count"] >= 1
    assert summary["rejection_types"]
    assert summary["statutory_deadline"]
    assert case["last_activity"]
    # Metadata only: nothing from the OA body leaks into the list.
    assert "UNIQUE-OA-MARKER" not in json.dumps(body, ensure_ascii=False)


def test_it_admin_is_refused_and_the_refusal_is_audited(gateway_client):
    token = _login(gateway_client, "carol")
    resp = _cases(gateway_client, token)
    assert resp.status_code == 403
    rows = audit.writer.list_for_tenant("tenant_b", limit=20)
    denied = [r for r in rows if r["endpoint"] == "/v1/cases"]
    assert denied, "a denied /v1/cases call must still write an audit row"
    assert denied[0]["policy_decisions"]["authz_passed"] is False


def test_every_call_writes_one_audit_row(gateway_client, alice_token):
    def count() -> int:
        return sum(
            1
            for r in audit.writer.list_for_tenant("tenant_a", limit=1000)
            if r["endpoint"] == "/v1/cases"
        )

    before = count()
    _cases(gateway_client, alice_token)
    assert count() == before + 1


def test_auditor_list_is_read_only(gateway_client):
    token = _login(gateway_client, "audit_dave")
    body = _cases(gateway_client, token).json()
    assert body["read_only"] is True
