"""Q16/Q17/Q19/Q21: the deadline inputs on /v1/oa/analyze reach the deadline
engine through the orchestrator, and deadline_summary carries the new fields."""

from __future__ import annotations

from pathlib import Path

import pytest

_SAMPLE_OA_CN = Path(__file__).resolve().parents[2] / "data" / "oa_samples" / "sample_oa_cn.txt"


def _analyze(gateway_client, token, **extra):
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "oa_text": _SAMPLE_OA_CN.read_text(encoding="utf-8"),
            "case_id": "CASE-2025-001",
            "target_patent_no": "CN123456789",
            **extra,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["deadline_summary"]


@pytest.mark.asyncio
async def test_deadline_fields_forwarded(gateway_client, alice_token, patched_ai_engine):
    d = _analyze(
        gateway_client,
        alice_token,
        oa_sequence=1,
        service_date="2025-04-20",
        applicant_domestic=True,
    )
    assert d["start_date"] == "2025-04-20"
    assert d["start_date_basis"] == "service_date"
    assert d["period_applied"].startswith("4 months")
    assert d["rules_reviewed"] is False
    assert d["mailing_date"]


@pytest.mark.asyncio
async def test_deadline_defaults_use_the_notice(gateway_client, alice_token, patched_ai_engine):
    d = _analyze(gateway_client, alice_token)
    # sample_oa_cn.txt prints "自本通知书发文日起四个月内" and no 送达日 / 第N次:
    # the stated period is used and the start is the presumed service date.
    assert d["period_applied"] == "4 months (stated in the notice)"
    assert d["start_date_basis"] == "presumed_service"
    assert any("presumed service" in a for a in d["assumptions"])
