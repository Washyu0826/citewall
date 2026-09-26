"""Q15/Q16 claim-element tables + Q14/Q17 sentence alignment through the
gateway → AI engine round trip (mock LLM, in-process AI engine).

The target patent is indexed directly into the AI engine's store so the claim
tree — the source of the claims the table charts — is populated.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_OA_US = _REPO_ROOT / "data" / "oa_samples" / "sample_oa_us.txt"


def _index_target(tenant: str = "tenant_a") -> None:
    from backend.ai_engine import rag
    from backend.shared.models import Patent

    rag.index_patent(
        tenant,
        Patent(
            patent_no="US17990001",
            title="Cooling system",
            abstract="A cooling system with a microchannel base plate.",
            claims=[
                "1. A cooling system, comprising: a base plate having microchannels; "
                "a pump connected to the microchannels; and a controller, wherein the "
                "controller adjusts a pump speed based on a sensed temperature.",
                "2. The cooling system of claim 1, wherein said microchannels are copper.",
            ],
            publication_date=datetime.fromisoformat("2024-01-01T00:00:00+00:00"),
            jurisdiction="US",
            is_local=False,
        ),
    )
    # A (fictitious) prior-art reference that discloses part of claim 1.
    rag.index_patent(
        tenant,
        Patent(
            patent_no="US9900001",
            title="Liquid cooled base plate",
            abstract="A cooling system has a base plate with microchannels and a pump "
            "connected to the microchannels to circulate coolant.",
            claims=[
                "1. A cooling system comprising a base plate with microchannels and a pump "
                "connected to the microchannels."
            ],
            publication_date=datetime.fromisoformat("2019-01-01T00:00:00+00:00"),
            jurisdiction="US",
            is_local=False,
        ),
    )


def _analyze(client, token, target: str = "US17990001"):
    resp = client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "oa_text": _SAMPLE_OA_US.read_text(encoding="utf-8"),
            "case_id": "CASE-2025-001",
            "target_patent_no": target,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def fresh_store():
    """The memory vector store is a process-global singleton that other tests
    fill; a fresh one keeps retrieval (and so the charted evidence) hermetic."""
    from backend.ai_engine import rag

    with rag.use_backends(store="memory"):
        yield


@pytest.mark.asyncio
async def test_element_tables_on_analyze_response(
    gateway_client, alice_token, patched_ai_engine, fresh_store
):
    _index_target()
    body = _analyze(gateway_client, alice_token)

    tables = body["element_tables"]
    assert tables, "an indexed target patent must yield at least one element table"
    rejection_ids = {r["rejection_id"] for r in body["oa"]["rejections"]}
    for t in tables:
        assert t["rejection_id"] in rejection_ids
        assert t["claim_no"] == 1  # the only independent claim
        assert t["method"] == "rules"  # mock mode never calls the model
        texts = [e["text"] for e in t["elements"]]
        assert texts[0] == "A cooling system"
        assert t["elements"][0]["is_preamble"] is True
        assert any(x.startswith("wherein the controller") for x in texts)
        assert t["evidence_available"] is True
        statuses = {e["status"] for e in t["elements"]}
        assert statuses <= {"disclosed", "partial", "not_disclosed"}
        # the prior art has base plate + pump but no temperature-controlled pump speed
        by_text = {e["text"]: e for e in t["elements"]}
        assert by_text["a base plate having microchannels"]["status"] == "disclosed"
        wherein = next(e for x, e in by_text.items() if x.startswith("wherein the controller"))
        assert wherein["status"] != "disclosed"
        assert wherein["missing_terms"]
        for e in t["elements"]:
            if e["evidence"] is not None:
                assert e["evidence"]["patent_no"] != "US17990001"  # never the target itself
            if e["evidence"] is not None:
                # ref_index resolves into this rejection's GROUNDED_REF numbering
                hits = [
                    h
                    for h in body["related_prior_art"]
                    if h["metadata"].get("rejection_id") == t["rejection_id"]
                ]
                assert 1 <= e["evidence"]["ref_index"] <= len(hits)
                hit = hits[e["evidence"]["ref_index"] - 1]
                assert hit["patent_no"] == e["evidence"]["patent_no"]


@pytest.mark.asyncio
async def test_no_tables_without_indexed_patent(gateway_client, alice_token, patched_ai_engine):
    body = _analyze(gateway_client, alice_token, target="US99999998")
    assert body["element_tables"] == []


@pytest.mark.asyncio
async def test_alignment_fields_on_drafts(gateway_client, alice_token, patched_ai_engine):
    body = _analyze(gateway_client, alice_token)
    for d in body["drafts"]:
        assert isinstance(d["alignment"], list)
        assert isinstance(d["unsupported_citations"], list)
        # every [UNSUPPORTED_REF_n] in the text is reported, and vice versa
        in_text = {
            f"[GROUNDED_REF_{n}]" for n in re.findall(r"\[UNSUPPORTED_REF_(\d+)\]", d["draft_text"])
        }
        assert in_text == set(d["unsupported_citations"])
        for row in d["alignment"]:
            assert row["status"] in {"supported", "unsupported", "unverifiable"}


@pytest.mark.asyncio
async def test_claim_text_is_redacted_before_element_comparison(
    gateway_client, alice_token, patched_ai_engine, monkeypatch, fresh_store
):
    """Invariant #3: claim text leaving the gateway for the decomposer is masked."""
    from backend.gateway import orchestrator

    _index_target()
    seen: list[dict] = []
    original = orchestrator.AIEngineClient.call

    async def spy(self, path, payload):
        if path == "/v1/element_comparison":
            seen.append(payload)
        return await original(self, path, payload)

    monkeypatch.setattr(orchestrator.AIEngineClient, "call", spy)
    from backend.gateway import masking

    calls: list[str] = []
    real_redact = masking.redact

    def tracking_redact(text, tenant_id):
        calls.append(text)
        return real_redact(text, tenant_id)

    monkeypatch.setattr(masking, "redact", tracking_redact)
    _analyze(gateway_client, alice_token)
    assert seen, "element comparison was not called"
    claim_texts = [c["text"] for c in seen[0]["claims"]]
    # every claim sent was produced by (i.e. passed through) redact()
    assert all(any(t == real_redact(orig, "tenant_a")[0] for orig in calls) for t in claim_texts)
