"""Q25 — named-entity masking (person / organisation / address).

Two properties matter equally:
  * identity in OA headers / signature blocks is masked before any LLM call;
  * technical content (claims, element names, statutes, chemistry, patent
    numbers) is NOT touched — over-masking corrupts the analysis.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from backend.gateway import masking

ROOT = Path(__file__).resolve().parents[2]
_PH = re.compile(r"\[[A-Z_]+_[0-9A-F]{8}\]")


@pytest.fixture(autouse=True)
def _rules_backend(monkeypatch):
    monkeypatch.setattr(masking.settings, "NER_BACKEND", "rules")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --- masks identity ---------------------------------------------------------


def test_tw_oa_header_identity_masked():
    red, rules = masking.redact(_read("data/oa_samples/sample_oa_tw.txt"), "tenant_a")
    for leaked in ("梁若蘅", "昕澄科技股份有限公司", "辛亥路"):
        assert leaked not in red
    assert {"ner_person", "ner_org", "ner_address"} <= set(rules)
    # (NFKC folds the fullwidth colon — pre-existing normalisation)
    assert "聯絡人:[PERSON_" in red
    assert "受文者:[ORG_" in red


def test_inventors_and_applicant_masked_in_publication():
    red, _ = masking.redact(_read("data/cases/CASE-DEMO-001/patent.txt"), "tenant_a")
    for name in ("方予辰", "葉承軒", "邱語彤", "韓致遠", "昕澄科技股份有限公司"):
        assert name not in red
    # each inventor gets its own placeholder, separators kept
    line = next(ln for ln in red.splitlines() if ln.startswith("發明人"))
    assert len(_PH.findall(line)) == 4
    assert line.count("、") == 3


def test_us_oa_applicant_and_examiner_masked():
    red, _ = masking.redact(_read("data/oa_samples/sample_oa_us.txt"), "tenant_a")
    assert "NCCU Apex Patent Law Firm" not in red
    assert "J. Smith" not in red
    assert "Examiner: [PERSON_" in red


@pytest.mark.parametrize(
    "text,leak",
    [
        ("Acme Widgets Co., Ltd. filed the reply.", "Acme Widgets"),
        ("Assignee: Stratum Networks Inc.", "Stratum Networks"),
        ("Please write to 10 Main Street, Suite 400 today.", "Main Street"),
        ("代理人：林雅婷專利師 已受任", "林雅婷"),
        ("本案由智眼科技股份有限公司提出", "智眼科技"),
        ("地址：新北市板橋區文化路一段 100 巷 5 號 2 樓", "文化路"),
        ("Attorney: John Smith, Esq.  Email: j@x.com", "John Smith"),
    ],
)
def test_identity_variants_masked(text, leak):
    red, _ = masking.redact(text, "tenant_a")
    assert leak not in red, red


# --- does NOT over-mask technical content -----------------------------------

TECHNICAL = [
    "電動車充電站之充電管理方法及系統",
    "該控制電路 3 號腳位輸出一驅動訊號",
    "電力公司之電網負載達到第一參考值時",
    "伺服器透過網路接收充電站之裝置資料與充電資料",
    "不符專利法第 26 條第 2 項之規定",
    "Claims 1-3 are rejected under 35 U.S.C. § 103 as being obvious over US7654321",
    "the microchannel cooling system with non-uniform cross-section",
    "a NaCl electrolyte and LiFePO4 cathode at 25 °C",
    "本公司之申請人主張請求項 1 具進步性",
    "該迴路 12 號節點與線路 3 號端子電性連接",
    "The Examiner Argument is traversed.",
]


@pytest.mark.parametrize("text", TECHNICAL)
def test_technical_text_untouched(text):
    red, rules = masking.redact(text, "tenant_a")
    assert red == masking.normalize_for_detection(text), red
    assert not [r for r in rules if r.startswith("ner_")]


def test_claims_section_of_every_demo_case_untouched():
    """Every claim line of the synthetic corpus survives NER unchanged."""
    checked = 0
    for patent in sorted((ROOT / "data/cases").glob("CASE-DEMO-*/patent.txt")):
        text = masking.normalize_for_detection(patent.read_text(encoding="utf-8"))
        marker = text.find("【申請專利範圍】")
        if marker == -1:
            continue
        claims = text[marker:]
        assert masking.ner_spans(claims) == [], patent.parent.name
        checked += 1
    assert checked >= 50


# --- mechanics --------------------------------------------------------------


def test_idempotent_on_placeholders():
    text = _read("data/oa_samples/sample_oa_tw.txt")
    once, _ = masking.redact(text, "tenant_a")
    twice, rules = masking.redact(once, "tenant_a")
    assert twice == once
    assert not [r for r in rules if r.startswith("ner_")]


def test_unmask_round_trip_restores_names():
    text = "發明人：方予辰、葉承軒\n受文者：昕澄科技股份有限公司"
    red, _ = masking.redact(text, "tenant_a")
    assert masking.unmask(red, "tenant_a") == masking.normalize_for_detection(text)


def test_backend_none_disables_ner(monkeypatch):
    monkeypatch.setattr(masking.settings, "NER_BACKEND", "none")
    red, rules = masking.redact("聯絡人：梁若蘅", "tenant_a")
    assert "梁若蘅" in red
    assert not [r for r in rules if r.startswith("ner_")]


def test_ckip_backend_falls_back_to_rules_when_unavailable(monkeypatch):
    monkeypatch.setattr(masking, "_ckip_driver", None)
    monkeypatch.setattr(masking, "_ckip_unavailable", False)
    # Make the optional import fail regardless of what is installed.
    monkeypatch.setitem(sys.modules, "ckip_transformers", None)
    monkeypatch.setitem(sys.modules, "ckip_transformers.nlp", None)
    spans = masking.ner_spans("聯絡人：梁若蘅", backend="ckip")
    assert [(s, e, label) for s, e, label in spans] == [(4, 7, "PERSON")]
    assert masking._ckip_unavailable is True


def test_ckip_backend_unions_model_spans(monkeypatch):
    class _Tok:
        def __init__(self, word, ner, idx):
            self.word, self.ner, self.idx = word, ner, idx

    def _fake_driver(batch, show_progress=False):
        return [
            [_Tok("王小明", "PERSON", (0, 3)), _Tok("台北", "GPE", (4, 6))]
            if "王小明" in ln
            else []
            for ln in batch
        ]

    monkeypatch.setattr(masking, "_ckip_driver", _fake_driver)
    monkeypatch.setattr(masking, "_ckip_unavailable", False)
    text = "第一行\n王小明在台北\n聯絡人：梁若蘅"
    spans = masking.ner_spans(text, backend="ckip")
    words = [text[s:e] for s, e, _ in spans]
    assert "王小明" in words  # from the model (line offset applied)
    assert "梁若蘅" in words  # from the rules
    assert "台北" not in words  # GPE is not masked
