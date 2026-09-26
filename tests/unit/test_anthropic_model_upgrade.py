"""Q1–Q5 (2026-09-25): Sonnet 5 / Haiku alias, anthropic SDK 1.x request
shape, Citations API drafting, structured outputs, per-loop client.

No network: a scripted fake stands in for ``AsyncAnthropic.messages``, but the
responses are REAL SDK types (``anthropic.types.Message`` / ``TextBlock`` /
``CitationCharLocation``) so the citation-mapping code is exercised against
the exact shape the API returns.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from anthropic.types import CitationCharLocation, Message, TextBlock, Usage

from backend.ai_engine import llm_client, oa_analyzer
from backend.ai_engine.llm_client import AnthropicLLM, LLMRefusalError
from backend.shared.config import settings
from backend.shared.models import Rejection, RejectionType, RetrievalHit

_SAMPLING = ("temperature", "top_p", "top_k")


def _msg(content, *, stop_reason="end_turn", model="claude-sonnet-5", **usage):
    blocks = [TextBlock(type="text", text=c) if isinstance(c, str) else c for c in content]
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model=model,
        content=blocks,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(
            input_tokens=usage.get("input_tokens", 100),
            output_tokens=usage.get("output_tokens", 20),
            cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
        ),
    )


def _cite(doc_index: int) -> CitationCharLocation:
    return CitationCharLocation(
        type="char_location",
        cited_text="cited",
        document_index=doc_index,
        document_title=f"[GROUNDED_REF_{doc_index + 1}]",
        start_char_index=0,
        end_char_index=5,
        file_id=None,
    )


class _Messages:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script.pop(0)


class _Client:
    def __init__(self, script):
        self.messages = _Messages(script)


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_SEC", 0.0)
    monkeypatch.setattr(settings, "LLM_RETRY_JITTER_SEC", 0.0)
    llm_client.reset_session_usage()

    def _make(script):
        inst = AnthropicLLM(api_key="dummy-key-no-network")
        inst._client = _Client(script)
        return inst

    return _make


def _run(inst, **kw):
    kw.setdefault("system", "SYS")
    kw.setdefault("user", "USER")
    kw.setdefault("security_level", "public")
    return asyncio.run(inst.achat(**kw))


# --- Q1/Q2 model defaults ----------------------------------------------------


def test_default_models_are_sonnet5_and_haiku_alias():
    from backend.shared import config

    fresh = config.Settings()
    assert fresh.LLM_MODEL_REASONING == "claude-sonnet-5"
    assert fresh.LLM_MODEL_VERIFIER == "claude-haiku-4-5"
    assert fresh.LLM_MODEL_CHEAP == "claude-haiku-4-5"
    # Alias, never a date-suffixed snapshot.
    assert not fresh.LLM_MODEL_VERIFIER.endswith("20251001")


def test_verifier_independence_holds_for_new_defaults(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    monkeypatch.setattr(settings, "LLM_MODEL_REASONING", "claude-sonnet-5")
    monkeypatch.setattr(settings, "LLM_MODEL_CHEAP", "claude-haiku-4-5")
    monkeypatch.setattr(settings, "LLM_MODEL_VERIFIER", "claude-haiku-4-5")
    llm_client.assert_verifier_independence()


def test_new_models_have_exact_pricing():
    from backend.gateway.rate_limit import cost_provenance_for

    assert cost_provenance_for("claude-sonnet-5") == "exact"
    assert cost_provenance_for("claude-haiku-4-5") == "exact"


# --- Q3 request shape: no sampling params, effort only where accepted --------


@pytest.mark.parametrize("intent", ["parse_oa", "draft_response", "verify_citations"])
def test_no_sampling_params_sent(llm, intent):
    inst = llm([_msg(["{}"])])
    _run(inst, intent=intent, model_hint="claude-sonnet-5")
    kwargs = inst._client.messages.calls[0]
    assert not any(k in kwargs for k in _SAMPLING)
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_effort_sent_to_sonnet_but_not_haiku(llm):
    inst = llm([_msg(["{}"]), _msg(["{}"], model="claude-haiku-4-5")])
    _run(inst, intent="draft_response", model_hint="claude-sonnet-5")
    _run(inst, intent="verify_citations", model_hint="claude-haiku-4-5")
    sonnet_kw, haiku_kw = inst._client.messages.calls
    assert sonnet_kw["output_config"]["effort"] == "high"
    assert "effort" not in haiku_kw["output_config"]


def test_vision_ocr_sends_no_sampling_params(llm):
    inst = llm([_msg(["page text"], model="claude-haiku-4-5")])
    text, _usage = asyncio.run(inst.vision_ocr(b"\x89PNG", "image/png"))
    assert text == "page text"
    assert not any(k in inst._client.messages.calls[0] for k in _SAMPLING)


# --- Q5 structured outputs ---------------------------------------------------


def test_parse_oa_uses_json_schema_with_rejection_enum(llm):
    inst = llm([_msg(['{"rejections": []}'])])
    _run(inst, intent="parse_oa", model_hint="claude-sonnet-5")
    fmt = inst._client.messages.calls[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    item = fmt["schema"]["properties"]["rejections"]["items"]
    assert set(item["properties"]["rejection_type"]["enum"]) == {t.value for t in RejectionType}
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])


def test_verify_citations_uses_json_schema(llm):
    inst = llm([_msg(["{}"], model="claude-haiku-4-5")])
    _run(inst, intent="verify_citations", model_hint="claude-haiku-4-5")
    schema = inst._client.messages.calls[0]["output_config"]["format"]["schema"]
    assert "verifier_confidence" in schema["required"]


def test_draft_without_documents_is_not_schema_constrained(llm):
    inst = llm([_msg(["{}"])])
    _run(inst, intent="draft_response", model_hint="claude-sonnet-5")
    assert "format" not in inst._client.messages.calls[0]["output_config"]


# --- Q4 Citations API --------------------------------------------------------

_DOCS = [
    {
        "ref": "[GROUNDED_REF_1]",
        "title": "[GROUNDED_REF_1] patent=TW1 section=claim_1",
        "text": "A",
    },
    {"ref": "[GROUNDED_REF_2]", "title": "[GROUNDED_REF_2] patent=US2 section=spec", "text": "B"},
]


def _cited_script():
    draft = _msg(
        [
            "【三、修正依據】修正依據見說明書",
            TextBlock(type="text", text="第[0012]段所載之充電流程", citations=[_cite(1)]),
            TextBlock(type="text", text="。", citations=[_cite(7)]),  # out of range
        ]
    )
    meta = _msg(['{"strategy": "以建立先行詞克服明確性瑕疵。", "confidence": 0.8}'])
    return [draft, meta]


def test_cited_draft_sends_documents_without_output_format(llm):
    inst = llm(_cited_script())
    _run(inst, intent="draft_response", model_hint="claude-sonnet-5", documents=_DOCS)
    first, second = inst._client.messages.calls
    content = first["messages"][0]["content"]
    docs = [b for b in content if b["type"] == "document"]
    assert [d["title"] for d in docs] == [d["title"] for d in _DOCS]
    assert all(d["citations"] == {"enabled": True} for d in docs)
    assert docs[0]["source"] == {"type": "text", "media_type": "text/plain", "data": "A"}
    # Citations and output_config.format cannot be combined (400).
    assert "format" not in first.get("output_config", {})
    # The overlay is a second, uncached system block after the cached prompt.
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Citations API" in first["system"][1]["text"]
    # Call 2 is the structured strategy/confidence extraction.
    assert second["output_config"]["format"]["schema"]["required"] == ["strategy", "confidence"]


def test_cited_draft_maps_document_index_to_grounded_ref(llm):
    inst = llm(_cited_script())
    resp = _run(inst, intent="draft_response", model_hint="claude-sonnet-5", documents=_DOCS)
    env = json.loads(resp.text)
    assert "第[0012]段所載之充電流程 [GROUNDED_REF_2]" in env["draft_text"]
    assert "[GROUNDED_REF_8]" not in env["draft_text"]  # out-of-range index ignored
    assert env["grounded_citations"] == ["[GROUNDED_REF_2]"]
    assert env["strategy"].startswith("以建立先行詞")
    assert env["confidence"] == 0.8
    # Usage is summed over both calls.
    assert resp.prompt_tokens == 200
    assert resp.completion_tokens == 40


def test_cited_marker_not_duplicated_when_model_wrote_it(llm):
    draft = _msg([TextBlock(type="text", text="依據 [GROUNDED_REF_1]", citations=[_cite(0)])])
    meta = _msg(['{"strategy": "s", "confidence": 0.5}'])
    inst = llm([draft, meta])
    resp = _run(inst, intent="draft_response", model_hint="claude-sonnet-5", documents=_DOCS)
    assert json.loads(resp.text)["draft_text"].count("[GROUNDED_REF_1]") == 1


def test_oa_analyzer_draft_goes_through_citations_in_anthropic_mode(monkeypatch, llm):
    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    monkeypatch.setattr(settings, "INJECTION_GUARD_ENABLED", True)
    inst = llm(_cited_script())
    monkeypatch.setattr(llm_client, "_get_anthropic_llm", lambda: inst)
    rejection = Rejection(
        rejection_id="rej-1",
        rejection_type=RejectionType.ANTECEDENT_BASIS,
        affected_claims=[9],
        cited_prior_art=[],
        examiner_argument="請求項9之『該第一電動車』未見有先行詞。",
        confidence=0.9,
    )
    hits = [
        RetrievalHit(patent_no="TW1", section="claim_1", text="A", score=0.9),
        RetrievalHit(patent_no="US2", section="spec", text="B", score=0.8),
    ]
    draft, meta = oa_analyzer.draft_response(rejection, hits, None, security_level="public")
    assert "[GROUNDED_REF_2]" in draft.draft_text
    assert draft.strategy
    assert meta["model_used"] == settings.LLM_MODEL_REASONING
    docs = [
        b
        for b in inst._client.messages.calls[0]["messages"][0]["content"]
        if b["type"] == "document"
    ]
    assert [d["title"].split()[0] for d in docs] == ["[GROUNDED_REF_1]", "[GROUNDED_REF_2]"]


def test_confidential_draft_never_reaches_cloud(monkeypatch, llm):
    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    inst = llm([])
    with pytest.raises(RuntimeError):
        _run(
            inst,
            intent="draft_response",
            model_hint="claude-sonnet-5",
            documents=_DOCS,
            security_level="confidential",
        )
    assert inst._client.messages.calls == []


# --- refusal / truncation ----------------------------------------------------


def test_refusal_stop_reason_raises(llm):
    inst = llm([_msg([""], stop_reason="refusal")])
    with pytest.raises(LLMRefusalError):
        _run(inst, intent="parse_oa", model_hint="claude-sonnet-5")
    assert llm_client.get_session_usage()["errors"] == 1


# --- per-loop client (review: asyncio.run + shared AsyncAnthropic) ----------


def test_client_is_per_event_loop():
    inst = AnthropicLLM(api_key="dummy-key-no-network")

    async def _grab():
        return inst._client, inst._client

    a1, a2 = asyncio.run(_grab())
    b1, _ = asyncio.run(_grab())
    assert a1 is a2  # same loop → reused (connection pooling)
    assert a1 is not b1  # new loop → new client, never a closed loop's pool
