"""Claim-element comparison table (Q15 / Q16 / Q18, 2026-09-25 decision).

For every rejected independent claim:

1. **Decompose** the claim into elements (limitations). Q18: the local model
   (qwen2.5:7b via ``llm_client``) proposes the split; the result is accepted
   only if every element is copied from the claim (``_llm_split_is_faithful``).
   Anything else — mock / dify mode, a model error, an unfaithful split — uses
   the deterministic splitter ``decompose_rules`` (preamble + 包含/comprising
   body split on ；; 、 and 其中/wherein boundaries).
2. **Map** each element to the best-supporting passage among the rejection's
   grounded prior-art hits (the same retrieval set the draft cites, so the
   table and the draft talk about the same passages).
3. **Label** each element ``disclosed`` / ``partial`` / ``not_disclosed`` with
   the evidence passage, the score and the element terms the passage never
   mentions (the "difference" the attorney argues from).

Scoring is the lexical support ratio from ``alignment.py`` (share of the
element's technical vocabulary found in the passage), plus the embedder cosine
when a real multilingual embedder is configured. Thresholds:

    disclosed      lexical >= 0.75  (or semantic >= 0.75)
    partial        lexical >= 0.30  (or semantic >= 0.60)
    not_disclosed  otherwise

An element is short, so "disclosed" demands most of its vocabulary in ONE
passage; "partial" means the passage covers some of it (typical of a 103
combination where another reference supplies the rest). The labels are
evidence for the attorney, not legal conclusions — the SPA shows them with the
"not reviewed by a patent attorney" framing and the raw passage.

Confidentiality: the gateway masks claim text before calling, and the LLM call
routes through ``llm_client.chat`` with the case's security_level, so a
confidential case never leaves the local model.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

from backend.ai_engine import alignment, llm_client
from backend.ai_engine.prompt_loader import render_system
from backend.shared.config import settings

logger = logging.getLogger(__name__)

DISCLOSED_LEXICAL = 0.75
PARTIAL_LEXICAL = 0.30
DISCLOSED_SEMANTIC = 0.75
PARTIAL_SEMANTIC = 0.60
SNIPPET_CHARS = 240
MAX_ELEMENTS = 20

_SYSTEM = render_system("claim_elements")

_CLAIM_NUM_PREFIX = re.compile(r"^\s*\d+\s*[\.\．、:：]\s*")
# Preamble / body boundary: "…，包含：" "…包括" "… comprising:" "…, which comprises"
_ZH_BODY_START = re.compile(r"[，,]?\s*(?:其(?:特徵在於|係)?)?(?:包含|包括|具有|係包含)\s*[：:]?")
_EN_BODY_START = re.compile(r",?\s*(?:which\s+)?compris(?:ing|es)\s*:?", re.IGNORECASE)
# Element separators inside the body.
_SEMICOLON = re.compile(r"[；;]\s*")
_ZH_WHEREIN = re.compile(r"[，,]?\s*(?=其中)")
_EN_WHEREIN = re.compile(r",?\s*(?=\bwherein\b)", re.IGNORECASE)
_LEADING_CONJ = re.compile(r"^(?:以及|及|與|和|且|and\s+|or\s+)", re.IGNORECASE)
_TRAILING_PUNCT = "，,。.；;：: \n\t"
_ENUM_COMMA = re.compile(r"、")
_MIN_ENUM_PART = 6  # only split on 、 when both parts are real clauses


def _clean(fragment: str) -> str:
    frag = fragment.strip().strip(_TRAILING_PUNCT)
    frag = _LEADING_CONJ.sub("", frag).strip().strip(_TRAILING_PUNCT)
    return frag


def _split_enumeration(fragment: str) -> list[str]:
    """Split "A、B" only when every part is clause-length (lists of short
    nouns like "銅、鋁及其合金" stay one element)."""
    parts = _ENUM_COMMA.split(fragment)
    if len(parts) > 1 and all(len(p.strip()) >= _MIN_ENUM_PART for p in parts):
        return parts
    return [fragment]


def decompose_rules(claim_text: str) -> list[str]:
    """Deterministic claim → elements split (mock mode / LLM fallback)."""
    # No NFKC here: elements are shown verbatim, so keep the claim's own
    # punctuation (the regexes accept both full- and half-width forms).
    text = _CLAIM_NUM_PREFIX.sub("", (claim_text or "").strip())
    if not text:
        return []
    m = _ZH_BODY_START.search(text) or _EN_BODY_START.search(text)
    elements: list[str] = []
    if m and m.start() > 0:
        preamble = _clean(text[: m.start()])
        body = text[m.end() :]
        if preamble:
            elements.append(preamble)
    else:
        body = text
    for chunk in _SEMICOLON.split(body):
        for sub in _ZH_WHEREIN.split(chunk):
            for sub2 in _EN_WHEREIN.split(sub):
                for part in _split_enumeration(sub2):
                    cleaned = _clean(part)
                    if cleaned:
                        elements.append(cleaned)
    return elements[:MAX_ELEMENTS]


def has_preamble(claim_text: str) -> bool:
    text = _CLAIM_NUM_PREFIX.sub("", unicodedata.normalize("NFKC", claim_text or "").strip())
    m = _ZH_BODY_START.search(text) or _EN_BODY_START.search(text)
    return bool(m and m.start() > 0)


def _llm_split_is_faithful(claim_text: str, elements: list[str]) -> bool:
    """Every element must be (near-)verbatim claim text: its content units are
    a subset of the claim's, and together they cover most of the claim."""
    if not elements or len(elements) > MAX_ELEMENTS:
        return False
    claim_units = alignment.content_units(claim_text)
    if not claim_units:
        return False
    covered: set[str] = set()
    for el in elements:
        if not isinstance(el, str) or not el.strip():
            return False
        units = alignment.content_units(el)
        if units and len(units - claim_units) / len(units) > 0.1:
            return False  # invented vocabulary
        covered |= units
    return len(covered & claim_units) / len(claim_units) >= 0.8


def _llm_enabled() -> bool:
    mode = (getattr(settings, "CLAIM_ELEMENTS_DECOMPOSER", "auto") or "auto").lower()
    if mode == "rules":
        return False
    if mode == "llm":
        return True
    # auto: only where a real model answers this intent directly. mock has no
    # real model; the Dify workflow app only implements parse/draft/verify.
    return settings.LLM_MODE in ("local", "anthropic")


def decompose(claim_text: str, *, security_level: str) -> tuple[list[str], str, str | None]:
    """Return (elements, method, model_used). method: "llm" | "rules"."""
    if _llm_enabled():
        try:
            resp = llm_client.chat(
                system=_SYSTEM,
                user=f"<untrusted_input>\n{claim_text}\n</untrusted_input>",
                intent="claim_elements",
                security_level=security_level,
            )
            if "-DEGRADED-" not in (resp.model or ""):
                data = _parse_json(resp.text)
                elements = [_clean(e) for e in (data.get("elements") or []) if isinstance(e, str)]
                elements = [e for e in elements if e]
                if _llm_split_is_faithful(claim_text, elements):
                    return elements[:MAX_ELEMENTS], "llm", resp.model
                logger.warning("claim_elements: LLM split rejected as unfaithful; using rules")
        except Exception as exc:  # noqa: BLE001 — deterministic fallback below
            logger.warning(
                "claim_elements: LLM decomposition failed (%s); using rules",
                exc.__class__.__name__,
            )
    return decompose_rules(claim_text), "rules", None


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _snippet(element: str, passage: str) -> str:
    """A window of ``passage`` around the first shared term."""
    if len(passage) <= SNIPPET_CHARS:
        return passage
    norm = alignment.normalise(passage)
    pos = -1
    for unit in sorted(alignment.content_units(element), key=len, reverse=True):
        pos = norm.find(unit)
        if pos >= 0:
            break
    if pos < 0:
        return passage[:SNIPPET_CHARS] + "…"
    start = max(0, pos - SNIPPET_CHARS // 3)
    end = min(len(passage), start + SNIPPET_CHARS)
    return ("…" if start else "") + passage[start:end] + ("…" if end < len(passage) else "")


def label(lexical: float, semantic: float | None) -> str:
    if lexical >= DISCLOSED_LEXICAL or (semantic is not None and semantic >= DISCLOSED_SEMANTIC):
        return "disclosed"
    if lexical >= PARTIAL_LEXICAL or (semantic is not None and semantic >= PARTIAL_SEMANTIC):
        return "partial"
    return "not_disclosed"


def map_element(
    element: str,
    hits: list[dict[str, Any]],
    *,
    embedder=None,
) -> dict[str, Any]:
    """Best-supporting hit for one element + status + missing terms.

    ``hits`` are grounded-set dicts (patent_no, section, text, …) in the
    rejection's GROUNDED_REF order — ``ref_index`` is that 1-based position so
    the SPA can resolve the passage exactly like a draft citation pill.
    """
    best: dict[str, Any] | None = None
    best_key = -1.0
    e_vec = None
    if embedder is not None:
        try:
            e_vec = embedder(element)
        except Exception:  # noqa: BLE001
            e_vec = None
    for i, hit in enumerate(hits):
        text = hit.get("text") or ""
        lex = alignment.support_ratio(element, text)
        sem = None
        if e_vec is not None:
            try:
                sem = alignment.cosine(e_vec, embedder(text))
            except Exception:  # noqa: BLE001
                sem = None
        key = max(lex, sem or 0.0)
        if key > best_key:
            best_key = key
            best = {"i": i, "hit": hit, "lex": lex, "sem": sem}
    if best is None:
        return {
            "status": "not_disclosed",
            "evidence": None,
            "lexical_support": 0.0,
            "semantic_similarity": None,
            "missing_terms": alignment.missing_terms(element, ""),
        }
    hit = best["hit"]
    status = label(best["lex"], best["sem"])
    return {
        "status": status,
        "evidence": {
            "ref_index": best["i"] + 1,
            "patent_no": hit.get("patent_no", ""),
            "section": hit.get("section", ""),
            "passage": _snippet(element, hit.get("text") or ""),
        },
        "lexical_support": round(best["lex"], 3),
        "semantic_similarity": None if best["sem"] is None else round(best["sem"], 3),
        "missing_terms": []
        if status == "disclosed"
        else alignment.missing_terms(element, hit.get("text") or ""),
    }


def target_claims(affected: list[int], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Independent claims to chart for a rejection: the affected independent
    claims, else the independent roots of the affected dependents."""
    by_no = {c.get("claim_no"): c for c in claims}
    picked: list[int] = []
    for no in affected:
        c = by_no.get(no)
        if c and c.get("is_independent") and no not in picked:
            picked.append(no)
    if not picked:
        for no in affected:
            seen: set[int] = set()
            c = by_no.get(no)
            while c and not c.get("is_independent") and c.get("depends_on") not in seen:
                seen.add(c.get("claim_no"))
                c = by_no.get(c.get("depends_on"))
            if c and c.get("is_independent") and c.get("claim_no") not in picked:
                picked.append(c.get("claim_no"))
    return [by_no[n] for n in picked]


def _norm_no(value: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


def compare_rejection(
    *,
    rejection: dict[str, Any],
    claims: list[dict[str, Any]],
    grounded_set: list[dict[str, Any]],
    security_level: str,
    target_patent_no: str = "",
) -> list[dict[str, Any]]:
    """Claim-element tables for one rejection (one per charted claim).

    Evidence never comes from the target patent itself (the tenant index holds
    it too, so retrieval can return its own claims — charting a claim against
    itself would read "disclosed" everywhere). When no prior-art text is left,
    rows are ``no_evidence`` instead of a misleading ``not_disclosed``.
    """
    target = _norm_no(target_patent_no)
    prior_art = [
        (i, h)
        for i, h in enumerate(grounded_set)
        if not target or _norm_no(h.get("patent_no")) != target
    ]
    cited = {_norm_no(p) for p in (rejection.get("cited_prior_art") or [])}
    # Rows point into the rejection's full grounded set (ref_index = GROUNDED_REF
    # number); prefer hits from the references the examiner actually cited.
    pool = [(i, h) for i, h in prior_art if _norm_no(h.get("patent_no")) in cited] or prior_art
    embedder = alignment.semantic_embedder()
    tables: list[dict[str, Any]] = []
    for claim in target_claims(list(rejection.get("affected_claims") or []), claims):
        elements, method, model = decompose(claim.get("text") or "", security_level=security_level)
        has_pre = has_preamble(claim.get("text") or "")
        rows = []
        for n, el in enumerate(elements, start=1):
            if not pool:
                rows.append(
                    {
                        "index": n,
                        "text": el,
                        "is_preamble": n == 1 and has_pre,
                        "status": "no_evidence",
                        "evidence": None,
                        "lexical_support": 0.0,
                        "semantic_similarity": None,
                        "missing_terms": [],
                    }
                )
                continue
            res = map_element(el, [h for _, h in pool], embedder=embedder)
            if res["evidence"] is not None:
                # translate the pool position back to the grounded-set position
                res["evidence"]["ref_index"] = pool[res["evidence"]["ref_index"] - 1][0] + 1
            rows.append({"index": n, "text": el, "is_preamble": n == 1 and has_pre, **res})
        tables.append(
            {
                "rejection_id": rejection.get("rejection_id", ""),
                "claim_no": claim.get("claim_no"),
                "method": method,
                "model_used": model,
                "evidence_available": bool(pool),
                "elements": rows,
            }
        )
    return tables
