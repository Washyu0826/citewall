"""POST /v1/oa/export_response — the whole OA response as one signed-off DOCX.

Same gates as /v1/oa/export (attorney authority, case ACL, exactly-True
sign-off), plus: a refused attempt by a non-attorney is audited (the role check
runs inside the audited frame), and the audit row never carries draft text.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile

from backend.gateway import audit

_CASE = "CASE-2025-001"
_KEPT = "申請人主張引證一未揭示非均勻截面之微通道。"
_DROPPED = "這句被律師排除，不得出現在文件中。"


def _login(client, user_id: str) -> str:
    resp = client.post("/v1/auth/login", json={"user_id": user_id, "password": f"demo-{user_id}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _body(signoff: bool = True, case_id: str = _CASE, accept_all: bool = True) -> dict:
    return {
        "case_id": case_id,
        "title": "申復理由書（草稿）",
        "attorney_signoff": signoff,
        "sections": [
            {
                "rejection_id": "rej-1",
                "heading": "一、進步性（請求項 1–3）",
                "segments": [
                    {
                        "segment_id": "s1",
                        "text": _KEPT,
                        "source": "ai_generated",
                        "accepted": accept_all,
                    },
                    {
                        "segment_id": "s2",
                        "text": _DROPPED,
                        "source": "ai_generated",
                        "accepted": False,
                    },
                ],
            },
            {
                "rejection_id": "rej-2",
                "heading": "二、新穎性（請求項 4–5）",
                "segments": [
                    {
                        "segment_id": "s3",
                        "text": "律師自行新增的論點。",
                        "source": "attorney_added",
                        "accepted": accept_all,
                    },
                ],
            },
        ],
    }


def _post(client, token, body):
    return client.post(
        "/v1/oa/export_response",
        headers={"Authorization": f"Bearer {token}", "X-Case-Id": body["case_id"]},
        json=body,
    )


def _audit_rows(tenant="tenant_a"):
    return [
        r
        for r in audit.writer.list_for_tenant(tenant, limit=200)
        if r["endpoint"] == "/v1/oa/export_response"
    ]


def test_attorney_gets_one_docx_with_only_accepted_sentences(gateway_client, alice_token):
    resp = _post(gateway_client, alice_token, _body())
    assert resp.status_code == 200, resp.text
    out = resp.json()

    assert out["section_count"] == 2
    assert out["filename"] == "CASE-2025-001-response.docx"
    assert _KEPT in out["document"] and _DROPPED not in out["document"]
    # The hash is over the canonical text, so it is reproducible.
    assert out["content_sha256"] == hashlib.sha256(out["document"].encode("utf-8")).hexdigest()

    with zipfile.ZipFile(io.BytesIO(base64.b64decode(out["docx_base64"]))) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "一、進步性（請求項 1–3）" in xml
    assert _KEPT in xml
    assert _DROPPED not in xml
    assert out["content_sha256"] in xml

    row = _audit_rows()[0]
    assert row["policy_decisions"]["attorney_signoff"] is True
    assert row["policy_decisions"]["prov_attorney_added"] == 1
    # Counts and hash only — never the draft text.
    assert _KEPT not in json.dumps(row, ensure_ascii=False)


def test_unticked_signoff_is_refused_and_audited(gateway_client, alice_token):
    before = len(_audit_rows())
    resp = _post(gateway_client, alice_token, _body(signoff=False))
    assert resp.status_code == 409
    rows = _audit_rows()
    assert len(rows) == before + 1
    assert rows[0]["policy_decisions"]["signoff_passed"] is False


def test_paralegal_cannot_sign_and_the_attempt_is_audited(gateway_client):
    token = _login(gateway_client, "bob")
    before = len(_audit_rows())
    resp = _post(gateway_client, token, _body())
    assert resp.status_code == 403
    assert len(_audit_rows()) == before + 1


def test_case_outside_acl_is_refused(gateway_client, alice_token):
    resp = _post(gateway_client, alice_token, _body(case_id="CASE-2099-999"))
    assert resp.status_code == 403


def test_nothing_accepted_is_rejected(gateway_client, alice_token):
    resp = _post(gateway_client, alice_token, _body(accept_all=False))
    assert resp.status_code == 422
