"""Sentence-level citation alignment (Q14 / Q17, 2026-09-25 decision).

The verifier's hard wall (``oa_analyzer.verify_citations``) only proves that a
``[GROUNDED_REF_n]`` token points at a hit that EXISTS in the grounded set. It
cannot tell whether the sentence carrying the token actually says something
the referenced passage supports — a local 7B model happily attaches a real
reference to a claim the reference never makes. There is no Citations API on
the local path (the user runs LLM_MODE=local only), so this module does the
check deterministically:

    for every draft sentence that carries [GROUNDED_REF_n]:
        score the sentence against hit n's text
        supported     -> keep the token
        unsupported   -> replace it with [UNSUPPORTED_REF_n]  (SPA blocks
                         direct acceptance, exactly like [CITATION_REMOVED])
        unverifiable  -> keep the token, report a warning (too little
                         content to judge, or the sentence and the passage
                         are in different scripts and no multilingual
                         embedder is available)

Scoring
-------
``lexical support`` = |content units of the sentence found in the passage| /
|content units of the sentence|. Content units are lowercased Latin content
words (claim boilerplate and stopwords removed) and CJK character BIGRAMS
(boilerplate bigrams removed) — the same granularity as claim_support.py's
§26 lint, so "the sentence's technical vocabulary appears in the passage" is
what is measured. When a real (multilingual) embedder is configured
(EMBEDDING_BACKEND=bge-m3|qwen3) the cosine similarity is used as a second
signal; the mock/lexical embedders are hash-based and say nothing about
meaning, so they are ignored.

Thresholds (see ``SUPPORT_THRESHOLD`` / ``EMBED_THRESHOLD``) are deliberately
low: response-brief sentences paraphrase and argue ("Ref 1 does not teach the
cooling plate"), so a sentence is only flagged when it shares almost none of
its technical vocabulary with the passage it cites — the fabricated-link case.
They are starting points to be tuned on real qwen2.5:7b drafts.

Pure functions, no I/O except the optional embedder call.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

from backend.ai_engine.claim_support import (
    _EN_CLAIM_STOPWORDS,
    _ZH_BOILERPLATE_BIGRAMS,
)
from backend.ai_engine.element_table import _EN_STOPWORDS

# A sentence is "supported" by a passage when at least this share of its
# content units appear in the passage. 0.20: a real grounded sentence in the
# mock + seed corpus scores 0.35-0.8; an unrelated sentence scores < 0.1.
SUPPORT_THRESHOLD = 0.25
# Multilingual embedder cosine that also counts as support (bge-m3 / Qwen3:
# unrelated patent passages sit around 0.3-0.45, paraphrases above 0.6).
EMBED_THRESHOLD = 0.55
# Fewer content units than this = too little to judge ("See [REF_1].").
MIN_UNITS = 3

GROUNDED_REF_RE = re.compile(r"\[GROUNDED_REF_(\d+)\]")
UNSUPPORTED_REF_FMT = "[UNSUPPORTED_REF_{n}]"
_ANY_MARKER_RE = re.compile(r"\[[A-Z_]+(?:_\d+)?\]")
_LATIN_WORD_RE = re.compile(r"[a-z][a-z\-]{1,}")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")

_LATIN_STOP = (
    set(_EN_STOPWORDS)
    | set(_EN_CLAIM_STOPWORDS)
    | {
        "see",
        "reference",
        "references",
        "ref",
        "cited",
        "patent",
        "discloses",
        "disclose",
        "disclosed",
        "teaches",
        "teach",
        "taught",
        "applicant",
        "examiner",
        "that",
        "this",
        "which",
        "does",
        "not",
        "also",
        "thus",
        "therefore",
        "furthermore",
        "moreover",
        "however",
        "explicitly",
        "respectfully",
        "away",
        "alone",
        "either",
        "claimed",
        "shown",
        "such",
    }
)
# Argument / citation glue that appears around ANY citation in a zh-TW brief.
_ZH_GLUE_BIGRAMS = set(_ZH_BOILERPLATE_BIGRAMS) | {
    "引證",
    "證一",
    "證二",
    "證三",
    "揭示",
    "揭露",
    "教示",
    "記載",
    "參見",
    "可見",
    "申請",
    "請人",
    "本案",
    "說明",
    "明書",
    "如上",
    "上揭",
    "因此",
    "故本",
    "並未",
    "未揭",
    "所揭",
}

_ZH_TERM_SPLIT_RE = re.compile(r"[之的及與或和並]")
# Characters trimmed from the edges of a reported missing term.
_ZH_FUNCTION_CHARS = "一其未已惟示設有為於在係將所該此揭教即亦則而但且故乃"
# Grammatical particles that never carry technical content (coverage scoring).
_ZH_PARTICLES = "之的及與或和並一其於在係將所該此即亦則而但且故乃為"

_SENTENCE_RE = re.compile(r"([。！？]|[.!?](?=\s))\s*")
_NON_TERMINAL_ABBREV = re.compile(
    r"(?:\b(?:U\.S\.C|U\.S|C\.F\.R|No|Nos|Fig|Figs|e\.g|i\.e|al|cf|Art|Sec|para|Ser|Pat|Appl)\.)$",
    re.IGNORECASE,
)


def normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").lower()


def _stem(word: str) -> str:
    """Crude plural fold so "channels" matches "channel" (no stemmer dep)."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def content_units(text: str) -> set[str]:
    """Latin content words + CJK bigrams, citation markers and glue removed."""
    t = normalise(_ANY_MARKER_RE.sub(" ", text or ""))
    units = {_stem(w) for w in _LATIN_WORD_RE.findall(t) if w not in _LATIN_STOP and len(w) > 2}
    for run in _CJK_RUN_RE.findall(t):
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg not in _ZH_GLUE_BIGRAMS:
                units.add(bg)
    return units


def _script(units: set[str]) -> str:
    has_cjk = any(_CJK_RUN_RE.fullmatch(u) for u in units)
    has_latin = any(not _CJK_RUN_RE.fullmatch(u) for u in units)
    if has_cjk and has_latin:
        return "mixed"
    return "cjk" if has_cjk else ("latin" if has_latin else "none")


def _latin_units(text: str) -> set[str]:
    t = normalise(_ANY_MARKER_RE.sub(" ", text or ""))
    return {_stem(w) for w in _LATIN_WORD_RE.findall(t) if w not in _LATIN_STOP and len(w) > 2}


def _cjk_coverage(text: str, p_units: set[str]) -> tuple[int, int]:
    """(covered, total) content characters of the CJK runs in ``text``.

    A content character is any Han character that is not a function
    character; it is covered when it sits inside a bigram the passage also
    contains (glue bigrams are not evidence). Character-level coverage keeps
    particles such as 於/該 from diluting the score the way a bigram ratio
    does ("形成於該冷卻板" has junk bigrams 於該/該冷 but every content
    character is in the passage).
    """
    t = normalise(_ANY_MARKER_RE.sub(" ", text or ""))
    covered_n = total = 0
    for run in _CJK_RUN_RE.findall(t):
        covered = [False] * len(run)
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg in p_units and bg not in _ZH_GLUE_BIGRAMS:
                covered[i] = covered[i + 1] = True
        glue = [False] * len(run)
        for i in range(len(run) - 1):
            if run[i : i + 2] in _ZH_GLUE_BIGRAMS:
                glue[i] = glue[i + 1] = True
        for ch, cov, gl in zip(run, covered, glue, strict=True):
            if ch in _ZH_PARTICLES or (gl and not cov):
                continue
            total += 1
            covered_n += cov
    return covered_n, total


def support_ratio(text: str, passage: str) -> float:
    """Share of ``text``'s technical content found in ``passage`` (0..1).

    Latin content words (plural-folded) count one each; CJK counts content
    characters covered by a shared bigram (see ``_cjk_coverage``).
    """
    p_units = content_units(passage)
    latin = _latin_units(text)
    c_cov, c_tot = _cjk_coverage(text, p_units)
    total = len(latin) + c_tot
    if not total:
        return 0.0
    return (len(latin & p_units) + c_cov) / total


def content_size(text: str) -> int:
    """Number of scoring units in ``text`` (Latin words + CJK content chars)."""
    return len(_latin_units(text)) + _cjk_coverage(text, set())[1]


def missing_terms(text: str, passage: str, limit: int = 5) -> list[str]:
    """Human-readable terms of ``text`` that ``passage`` never mentions.

    Latin: whole content words. CJK: a character counts as covered when it is
    part of a bigram the passage also contains (or of a glue bigram); maximal
    runs of UNcovered characters are the missing terms ("一種電池冷卻裝置" vs a
    passage about 電池冷卻 -> "裝置"), split on connective particles and trimmed
    of function characters.
    """
    t = normalise(_ANY_MARKER_RE.sub(" ", text or ""))
    p_units = content_units(passage)
    out: list[str] = []
    for w in _LATIN_WORD_RE.findall(t):
        stem = _stem(w)
        if w not in _LATIN_STOP and len(w) > 2 and stem not in p_units and w not in out:
            out.append(w)
    for run in _CJK_RUN_RE.findall(t):
        covered = [False] * len(run)
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg in _ZH_GLUE_BIGRAMS or bg in p_units:
                covered[i] = covered[i + 1] = True
        cur = ""
        segments: list[str] = []
        for ch, cov in zip(run, covered, strict=True):
            if cov:
                segments.append(cur)
                cur = ""
            else:
                cur += ch
        segments.append(cur)
        for seg in segments:
            for term in _ZH_TERM_SPLIT_RE.split(seg):
                term = term.strip(_ZH_FUNCTION_CHARS)
                if len(term) >= 2 and term not in out:
                    out.append(term)
    return out[:limit]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=False))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


def semantic_embedder() -> Callable[[str], list[float]] | None:
    """The configured embedder, but only when it carries meaning.

    mock / lexical embedders are hash-based: their cosine is noise for this
    purpose, so alignment falls back to lexical support alone.
    """
    from backend.shared.config import settings

    backend = (getattr(settings, "EMBEDDING_BACKEND", "mock") or "mock").lower()
    if backend in ("mock", "lexical"):
        return None
    try:
        from backend.ai_engine import rag
    except Exception:  # noqa: BLE001 — optional signal only
        return None

    def _embed(text: str) -> list[float]:
        return rag.embed(text)

    return _embed


def split_sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) spans of sentences in ``text`` — same rules as the SPA's
    ``splitIntoLines`` (CJK terminators with or without a following space;
    western . ! ? only before whitespace and not after a known abbreviation).
    Spans cover the original text exactly, so edits can be spliced back."""
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENTENCE_RE.finditer(text):
        end = m.start() + len(m.group(1))
        if m.group(1) == "." and _NON_TERMINAL_ABBREV.search(text[start:end]):
            continue
        spans.append((start, end))
        start = m.end()
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    return spans


@dataclass
class RefAlignment:
    sentence_index: int
    ref: str  # "[GROUNDED_REF_n]"
    status: str  # supported | unsupported | unverifiable
    lexical_support: float
    semantic_similarity: float | None
    reason: str
    missing_terms: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def assess(
    sentence: str,
    passage: str,
    *,
    embedder: Callable[[str], list[float]] | None = None,
) -> tuple[str, float, float | None, str]:
    """Return (status, lexical_support, semantic_similarity, reason)."""
    s_units = content_units(sentence)
    lex = support_ratio(sentence, passage)
    size = content_size(sentence)
    sem: float | None = None
    if embedder is not None:
        try:
            sem = cosine(embedder(sentence), embedder(passage))
        except Exception:  # noqa: BLE001 — embedder is an optional signal
            sem = None
    if lex >= SUPPORT_THRESHOLD:
        return "supported", lex, sem, "lexical"
    if sem is not None and sem >= EMBED_THRESHOLD:
        return "supported", lex, sem, "semantic"
    if size < MIN_UNITS:
        return "unverifiable", lex, sem, "too_short"
    p_script = _script(content_units(passage))
    s_script = _script(s_units)
    if sem is None and {s_script, p_script} == {"latin", "cjk"}:
        return "unverifiable", lex, sem, "cross_script"
    return "unsupported", lex, sem, "low_overlap"


def align_draft(
    draft_text: str,
    passages: dict[int, str],
    *,
    embedder: Callable[[str], list[float]] | None = None,
) -> tuple[str, list[dict]]:
    """Check every [GROUNDED_REF_n] against passage n; mark unsupported ones.

    ``passages`` maps the 1-based ref number to the grounded hit's text. A ref
    with no passage is left alone (the hard wall already handles those).
    Returns (annotated_text, alignment rows).
    """
    rows: list[dict] = []
    pieces: list[str] = []
    cursor = 0
    for idx, (start, end) in enumerate(split_sentences(draft_text)):
        pieces.append(draft_text[cursor:start])
        sentence = draft_text[start:end]
        new_sentence = sentence
        for m in GROUNDED_REF_RE.finditer(sentence):
            n = int(m.group(1))
            passage = passages.get(n)
            if passage is None:
                continue
            status, lex, sem, reason = assess(sentence, passage, embedder=embedder)
            rows.append(
                RefAlignment(
                    sentence_index=idx,
                    ref=m.group(0),
                    status=status,
                    lexical_support=round(lex, 3),
                    semantic_similarity=None if sem is None else round(sem, 3),
                    reason=reason,
                    missing_terms=missing_terms(sentence, passage) if status != "supported" else [],
                ).to_dict()
            )
            if status == "unsupported":
                new_sentence = new_sentence.replace(m.group(0), UNSUPPORTED_REF_FMT.format(n=n), 1)
        pieces.append(new_sentence)
        cursor = end
    pieces.append(draft_text[cursor:])
    return "".join(pieces), rows
