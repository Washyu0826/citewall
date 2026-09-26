"""Q15/Q16/Q18 claim-element table + Q14/Q17 sentence alignment — pure logic."""

from __future__ import annotations

import pytest

from backend.ai_engine import alignment, claim_elements
from backend.ai_engine.llm_client import LLMResponse

ZH_CLAIM = (
    "1. 一種電池冷卻裝置，包含：一冷卻板，設置於一電池模組下方；一冷卻液流道，形成於該冷卻板內；"
    "以及一泵浦，連接該冷卻液流道，其中該泵浦依據電池溫度調整流量。"
)
EN_CLAIM = (
    "1. A battery cooling device, comprising: a cooling plate disposed under a battery module; "
    "a coolant channel formed in the cooling plate; and a pump connected to the coolant channel, "
    "wherein the pump adjusts a flow rate based on a battery temperature."
)
HITS = [
    {
        "patent_no": "US9900002",
        "section": "spec",
        "text": "The battery pack includes a cooling plate beneath the module with coolant channels.",
    },
    {
        "patent_no": "TW099000123",
        "section": "spec",
        "text": "本發明之散熱系統包含一冷卻板設置於電池模組下方，冷卻板內形成冷卻液流道。",
    },
]


# ---------------------------------------------------------------- decompose


def test_decompose_rules_zh_splits_preamble_semicolons_and_wherein():
    els = claim_elements.decompose_rules(ZH_CLAIM)
    assert els == [
        "一種電池冷卻裝置",
        "一冷卻板，設置於一電池模組下方",
        "一冷卻液流道，形成於該冷卻板內",
        "一泵浦，連接該冷卻液流道",
        "其中該泵浦依據電池溫度調整流量",
    ]
    assert claim_elements.has_preamble(ZH_CLAIM)


def test_decompose_rules_en():
    els = claim_elements.decompose_rules(EN_CLAIM)
    assert els[0] == "A battery cooling device"
    assert "a coolant channel formed in the cooling plate" in els
    assert els[-1].startswith("wherein the pump adjusts")
    assert not any(e.startswith("and ") for e in els)


def test_enumeration_comma_only_splits_clause_length_parts():
    assert claim_elements.decompose_rules("一種合金，包含銅、鋁及其合金") == [
        "一種合金",
        "銅、鋁及其合金",
    ]
    long_enum = "一種系統，包含：一感測器量測電池溫度、一控制器依溫度調整泵浦"
    assert claim_elements.decompose_rules(long_enum) == [
        "一種系統",
        "一感測器量測電池溫度",
        "一控制器依溫度調整泵浦",
    ]


def test_no_preamble_marker_keeps_single_body():
    assert claim_elements.decompose_rules("A widget having a hinge") == ["A widget having a hinge"]
    assert not claim_elements.has_preamble("A widget having a hinge")


def test_faithfulness_check_rejects_invented_or_partial_splits():
    good = claim_elements.decompose_rules(EN_CLAIM)
    assert claim_elements._llm_split_is_faithful(EN_CLAIM, good)
    assert not claim_elements._llm_split_is_faithful(EN_CLAIM, good + ["a graphene heat spreader"])
    assert not claim_elements._llm_split_is_faithful(EN_CLAIM, good[:1])  # covers too little
    assert not claim_elements._llm_split_is_faithful(EN_CLAIM, [])


class _FakeLLM:
    def __init__(self, text, model="qwen2.5:7b"):
        self.text, self.model, self.calls = text, model, []

    def __call__(self, **kw):
        self.calls.append(kw)
        return LLMResponse(
            text=self.text, model=self.model, prompt_tokens=1, completion_tokens=1, latency_ms=1
        )


def _use_llm(monkeypatch, fake):
    monkeypatch.setattr(claim_elements.settings, "LLM_MODE", "local")
    monkeypatch.setattr(claim_elements.settings, "CLAIM_ELEMENTS_DECOMPOSER", "auto")
    monkeypatch.setattr(claim_elements.llm_client, "chat", fake)


def test_llm_decomposition_used_when_faithful(monkeypatch):
    split = claim_elements.decompose_rules(EN_CLAIM)
    fake = _FakeLLM('{"elements": ' + __import__("json").dumps(split) + "}")
    _use_llm(monkeypatch, fake)
    els, method, model = claim_elements.decompose(EN_CLAIM, security_level="confidential")
    assert (els, method, model) == (split, "llm", "qwen2.5:7b")
    # routed with the case's security level and the claim spotlighted as data
    assert fake.calls[0]["security_level"] == "confidential"
    assert fake.calls[0]["intent"] == "claim_elements"
    assert "<untrusted_input>" in fake.calls[0]["user"]


@pytest.mark.parametrize(
    "reply,model",
    [
        ('{"elements": ["a quantum flux capacitor"]}', "qwen2.5:7b"),  # invented
        ("not json at all", "qwen2.5:7b"),
        ('{"elements": ["A battery cooling device"]}', "qwen2.5:7b-DEGRADED-mock"),  # degraded
    ],
)
def test_llm_decomposition_falls_back_to_rules(monkeypatch, reply, model):
    _use_llm(monkeypatch, _FakeLLM(reply, model))
    els, method, _ = claim_elements.decompose(EN_CLAIM, security_level="public")
    assert method == "rules"
    assert els == claim_elements.decompose_rules(EN_CLAIM)


def test_llm_error_falls_back(monkeypatch):
    def boom(**_):
        raise RuntimeError("ollama down")

    _use_llm(monkeypatch, boom)
    assert claim_elements.decompose(ZH_CLAIM, security_level="public")[1] == "rules"


def test_mock_mode_never_calls_model(monkeypatch):
    fake = _FakeLLM("{}")
    monkeypatch.setattr(claim_elements.settings, "LLM_MODE", "mock")
    monkeypatch.setattr(claim_elements.llm_client, "chat", fake)
    assert claim_elements.decompose(EN_CLAIM, security_level="public")[1] == "rules"
    assert fake.calls == []


# ---------------------------------------------------------------- map / label


@pytest.mark.parametrize(
    "lex,sem,expected",
    [
        (0.8, None, "disclosed"),
        (0.75, None, "disclosed"),
        (0.5, None, "partial"),
        (0.3, None, "partial"),
        (0.1, None, "not_disclosed"),
        (0.1, 0.8, "disclosed"),
        (0.1, 0.65, "partial"),
    ],
)
def test_label_thresholds(lex, sem, expected):
    assert claim_elements.label(lex, sem) == expected


def test_map_elements_zh_and_en():
    cases = {
        "一冷卻板，設置於一電池模組下方": ("disclosed", []),
        "一泵浦，連接該冷卻液流道": ("partial", ["泵浦", "連接"]),
        "其中該泵浦依據電池溫度調整流量": ("not_disclosed", ["泵浦", "溫度調整流量"]),
        "a cooling plate disposed under a battery module": ("disclosed", []),
        "a pump connected to the coolant channel": ("partial", ["pump"]),
    }
    for element, (status, missing) in cases.items():
        res = claim_elements.map_element(element, HITS)
        assert res["status"] == status, (element, res)
        assert res["missing_terms"] == missing, (element, res)
    best = claim_elements.map_element("一冷卻板，設置於一電池模組下方", HITS)["evidence"]
    assert best["ref_index"] == 2 and best["patent_no"] == "TW099000123"


def test_target_claims_prefers_affected_independent_then_roots():
    claims = [
        {"claim_no": 1, "is_independent": True, "depends_on": None, "text": "c1"},
        {"claim_no": 2, "is_independent": False, "depends_on": 1, "text": "c2"},
        {"claim_no": 3, "is_independent": False, "depends_on": 2, "text": "c3"},
        {"claim_no": 4, "is_independent": True, "depends_on": None, "text": "c4"},
    ]
    assert [c["claim_no"] for c in claim_elements.target_claims([1, 2, 4], claims)] == [1, 4]
    assert [c["claim_no"] for c in claim_elements.target_claims([3], claims)] == [1]
    assert claim_elements.target_claims([9], claims) == []


def test_compare_rejection_excludes_target_and_reports_no_evidence():
    claims = [{"claim_no": 1, "is_independent": True, "depends_on": None, "text": EN_CLAIM}]
    rej = {"rejection_id": "rej-1", "affected_claims": [1], "cited_prior_art": []}
    own = [{"patent_no": "US-17123456", "section": "claim_1", "text": EN_CLAIM}]
    [t] = claim_elements.compare_rejection(
        rejection=rej,
        claims=claims,
        grounded_set=own,
        security_level="public",
        target_patent_no="US17123456",
    )
    assert t["evidence_available"] is False
    assert {e["status"] for e in t["elements"]} == {"no_evidence"}

    [t] = claim_elements.compare_rejection(
        rejection=rej,
        claims=claims,
        grounded_set=own + HITS,
        security_level="public",
        target_patent_no="US17123456",
    )
    assert t["evidence_available"] is True
    # ref_index points into the FULL grounded set (target at position 1)
    refs = {e["evidence"]["ref_index"] for e in t["elements"] if e["evidence"]}
    assert refs <= {2, 3}


def test_compare_rejection_prefers_examiner_cited_references():
    claims = [{"claim_no": 1, "is_independent": True, "depends_on": None, "text": ZH_CLAIM}]
    rej = {"rejection_id": "r", "affected_claims": [1], "cited_prior_art": ["US 9900002"]}
    [t] = claim_elements.compare_rejection(
        rejection=rej, claims=claims, grounded_set=HITS, security_level="public"
    )
    assert {e["evidence"]["patent_no"] for e in t["elements"]} == {"US9900002"}


# ---------------------------------------------------------------- alignment

PASSAGE = "本發明之散熱模組包含一冷卻板，冷卻板內設有冷卻液流道，流道連接至電池模組底部。"


def test_split_sentences_matches_spa_rules():
    text = "Claim 1 is rejected under 35 U.S.C. § 103. See Patent No. X. 本案具進步性。另見圖2！"
    spans = alignment.split_sentences(text)
    assert [text[a:b] for a, b in spans] == [
        "Claim 1 is rejected under 35 U.S.C. § 103.",
        "See Patent No. X.",
        "本案具進步性。",
        "另見圖2！",
    ]


@pytest.mark.parametrize(
    "sentence,status,reason",
    [
        ("引證1揭示一冷卻板內設冷卻液流道 [GROUNDED_REF_1]。", "supported", "lexical"),
        ("引證1已教示無線充電線圈之諧振頻率調整 [GROUNDED_REF_1]。", "unsupported", "low_overlap"),
        ("See [GROUNDED_REF_1].", "unverifiable", "too_short"),
        (
            "Reference 1 teaches a cooling plate with coolant channels [GROUNDED_REF_1].",
            "unverifiable",
            "cross_script",
        ),
    ],
)
def test_assess(sentence, status, reason):
    got = alignment.assess(sentence, PASSAGE)
    assert (got[0], got[3]) == (status, reason)


def test_semantic_signal_rescues_paraphrase():
    same = alignment.assess(
        "Reference 1 teaches a cooling plate with coolant channels [GROUNDED_REF_1].",
        PASSAGE,
        embedder=lambda _t: [1.0, 0.0],
    )
    assert same[0] == "supported" and same[3] == "semantic"


def test_align_draft_rewrites_only_unsupported_refs_and_preserves_text():
    draft = "申請人認為引證1揭示冷卻板 [GROUNDED_REF_1]。惟其未教示無線充電線圈 [GROUNDED_REF_1]。See [GROUNDED_REF_9]."
    out, rows = alignment.align_draft(draft, {1: PASSAGE})
    assert out == draft.replace("無線充電線圈 [GROUNDED_REF_1]", "無線充電線圈 [UNSUPPORTED_REF_1]")
    assert [r["status"] for r in rows] == ["supported", "unsupported"]  # REF_9 has no passage
    assert rows[1]["missing_terms"] == ["無線充電線圈"]


def test_missing_terms_are_readable():
    assert alignment.missing_terms("一種電池冷卻裝置", "電池冷卻") == ["裝置"]
    assert alignment.missing_terms("a pump connected to coolant channels", "coolant channel") == [
        "pump"
    ]
