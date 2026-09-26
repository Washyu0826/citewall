"""Retrieval upgrade (Q9–Q13, Q39): sparse encoding, contextual retrieval,
qwen3 embedder wiring, reranker hook, Qdrant v2 hybrid (local mode) + legacy
migration, and the public prior-art eval set with its negative control.

No model downloads and no docker: Qdrant runs in qdrant-client local mode
(":memory:"), heavy models are replaced by fakes at their seams."""

from __future__ import annotations

import types
from datetime import datetime

import pytest

from backend.ai_engine import rag, retrieval_eval
from backend.shared.config import settings
from backend.shared.models import Patent


def _patent(no, title, abstract, claims, year=2010):
    return Patent(
        patent_no=no,
        title=title,
        abstract=abstract,
        claims=claims,
        publication_date=datetime(year, 1, 1),
        jurisdiction="US",
        is_local=False,
    )


BATTERY = _patent(
    "US1",
    "Liquid-cooled battery module",
    "A battery module with a cooling plate having coolant channels.",
    [
        "A battery module comprising a cooling plate with serpentine coolant channels.",
        "The battery module of claim 1, wherein the coolant is glycol.",
    ],
)
HEATSINK = _patent(
    "US2",
    "Finned heat sink",
    "An extruded aluminium heat sink with parallel fins for power transistors.",
    ["A heat sink comprising a base and parallel extruded fins."],
)


# ---------------------------------------------------------------------------
# sparse encoding
# ---------------------------------------------------------------------------


def test_sparse_encode_is_deterministic_and_query_weighted():
    i1, v1 = rag.sparse_encode("cooling plate cooling channel")
    i2, v2 = rag.sparse_encode("cooling plate cooling channel")
    assert (i1, v1) == (i2, v2)
    # "cooling" appears twice → higher saturated tf than single terms.
    tf = dict(zip(i1, v1, strict=True))
    assert tf[rag._sparse_index("w:cooling")] > tf[rag._sparse_index("w:plate")]
    qi, qv = rag.sparse_encode("cooling plate cooling", is_query=True)
    assert set(qv) == {1.0} and len(qi) == 2


def test_sparse_encode_cjk_bigrams():
    idx, _ = rag.sparse_encode("冷卻板")
    # CJK text is tokenised into bigrams (same tokenizer as the memory BM25).
    assert len(idx) >= 2


# ---------------------------------------------------------------------------
# contextual retrieval (Q13)
# ---------------------------------------------------------------------------


def test_template_context_labels_claims_and_keeps_text():
    chunks = rag.chunk_patent(BATTERY)
    rag.contextualize(chunks, BATTERY, security_level="public")
    by_sec = {c.section: c for c in chunks}
    c1, c2 = by_sec["claim_1"], by_sec["claim_2"]
    assert "Liquid-cooled battery module" in c1.metadata["context"]
    assert "independent" in c1.metadata["context"]
    assert "dependent" in c2.metadata["context"] and "independent" not in c2.metadata["context"]
    # Displayed / grounded text is untouched; only the index text gains context.
    assert c1.text.startswith("A battery module")
    assert rag.index_text(c1).startswith(c1.metadata["context"])


def test_contextual_off(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXTUAL_RETRIEVAL", "off")
    chunks = rag.chunk_patent(BATTERY)
    rag.contextualize(chunks, BATTERY)
    assert all("context" not in c.metadata for c in chunks)
    assert rag.index_text(chunks[0]) == chunks[0].text


def test_llm_context_is_template_in_mock_mode(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXTUAL_RETRIEVAL", "llm")
    monkeypatch.setattr(settings, "LLM_MODE", "mock")
    chunks = rag.chunk_patent(BATTERY)
    rag.contextualize(chunks, BATTERY)
    assert chunks[0].metadata["context"] == rag.template_context(chunks[0], BATTERY.title)


def test_llm_context_routes_security_level_and_caches(monkeypatch, tmp_path):
    from backend.ai_engine import llm_client

    monkeypatch.setattr(settings, "CONTEXTUAL_RETRIEVAL", "llm")
    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    monkeypatch.setattr(settings, "CONTEXT_CACHE_DIR", str(tmp_path))
    calls = []

    def fake_chat(**kw):
        calls.append(kw)
        return types.SimpleNamespace(text="Claim 1: the cooling plate.", model="local-x")

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    chunk = rag.chunk_patent(BATTERY)[0]
    ctx = rag.llm_context(chunk, BATTERY.title, BATTERY.abstract, "confidential")
    assert "Claim 1: the cooling plate." in ctx
    assert calls[0]["security_level"] == "confidential"  # → local model (route_model)
    assert "<untrusted_input>" in calls[0]["user"]
    # Second call is served from the on-disk cache (no new LLM call).
    assert rag.llm_context(chunk, BATTERY.title, BATTERY.abstract, "confidential") == ctx
    assert len(calls) == 1
    assert list(tmp_path.glob("*.json"))


def test_llm_context_falls_back_on_failure_and_degraded(monkeypatch, tmp_path):
    from backend.ai_engine import llm_client

    monkeypatch.setattr(settings, "LLM_MODE", "local")
    monkeypatch.setattr(settings, "CONTEXT_CACHE_DIR", str(tmp_path))
    chunk = rag.chunk_patent(BATTERY)[0]
    template = rag.template_context(chunk, BATTERY.title)

    def boom(**kw):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(llm_client, "chat", boom)
    assert rag.llm_context(chunk, BATTERY.title, "", "public") == template
    monkeypatch.setattr(
        llm_client,
        "chat",
        lambda **kw: types.SimpleNamespace(text="junk", model="qwen-DEGRADED-mock"),
    )
    assert rag.llm_context(chunk, BATTERY.title, "", "public") == template
    assert not list(tmp_path.glob("*.json"))  # fallbacks are never cached


def test_index_patent_defaults_fail_closed(monkeypatch):
    seen = []
    monkeypatch.setattr(
        rag, "contextualize", lambda ch, p, security_level: seen.append(security_level)
    )
    with rag.use_backends(embedding="lexical"):
        rag.index_patent("t", BATTERY)
    assert seen == ["confidential"]


# ---------------------------------------------------------------------------
# Q9 embedder wiring (no model download)
# ---------------------------------------------------------------------------


class _FakeST:
    def __init__(self):
        self.calls = []

    def encode(self, text, **kw):
        import numpy as np

        self.calls.append(text)
        return np.ones(4, dtype="float32") / 2.0

    def get_sentence_embedding_dimension(self):
        return 4


def test_qwen3_embedder_is_lazy_and_prompts_queries_only():
    emb = rag.Embedder(backend="qwen3")
    assert emb._st_model is None  # nothing loaded at construction
    emb._st_model = _FakeST()
    emb.embed_one("a cooling plate", tenant_id="t")
    emb.embed_one("a cooling plate", tenant_id="t", is_query=True)
    doc_call, query_call = emb._st_model.calls
    assert doc_call == "a cooling plate"
    assert query_call.startswith("Instruct:") and query_call.endswith("a cooling plate")
    assert emb.dim == 4


def test_symmetric_backends_ignore_is_query():
    emb = rag.Embedder(backend="lexical")
    assert emb.embed_one("x y z", "t") == emb.embed_one("x y z", "t", is_query=True)


def test_pick_device_respects_explicit_and_insufficient_vram():
    assert rag.pick_device("cpu", 1) == "cpu"
    assert rag.pick_device("cuda", 1) == "cuda"
    # No card has a petabyte free: auto must fall back to CPU.
    assert rag.pick_device("auto", 1e6) == "cpu"


# ---------------------------------------------------------------------------
# Q10 reranker hook
# ---------------------------------------------------------------------------


class _ReverseReranker:
    enabled = True
    backend = "fake"

    def __init__(self):
        self.pool_sizes = []

    def rerank(self, query, hits):
        self.pool_sizes.append(len(hits))
        return [(ch, float(i)) for i, (ch, _s) in enumerate(hits)][::-1]


def test_retrieve_applies_reranker_over_candidate_pool(monkeypatch):
    fake = _ReverseReranker()
    with rag.use_backends(embedding="lexical"):
        rag.index_patent("t", BATTERY, security_level="public")
        rag.index_patent("t", HEATSINK, security_level="public")
        baseline = rag.retrieve("t", "coolant channel cooling plate", top_k=2, hybrid=False)
        monkeypatch.setattr(rag, "_reranker", fake)
        reranked = rag.retrieve("t", "coolant channel cooling plate", top_k=2, hybrid=False)
    # The reranker saw the whole over-fetched pool, not just top_k …
    assert fake.pool_sizes and fake.pool_sizes[0] > 2
    # … and its order (reverse) replaced the dense order.
    assert [h.metadata["chunk_id"] for h in reranked] != [h.metadata["chunk_id"] for h in baseline]


def test_reranker_none_is_identity():
    r = rag.Reranker(backend="none")
    hits = [(rag.chunk_patent(BATTERY)[0], 0.5)]
    assert r.rerank("q", hits) is hits


# ---------------------------------------------------------------------------
# Q11 Qdrant v2 hybrid (qdrant-client local mode)
# ---------------------------------------------------------------------------


@pytest.fixture
def qdrant_local():
    pytest.importorskip("qdrant_client")
    with rag.use_backends(embedding="lexical", store="qdrant::memory:") as ctx:
        yield ctx


def test_qdrant_v2_schema_and_hybrid(qdrant_local):
    rag.index_patent("t", BATTERY, security_level="public")
    rag.index_patent("t", HEATSINK, security_level="public")
    store = rag._store
    info = store._client.get_collection(collection_name=store._coll("t"))
    assert "dense" in info.config.params.vectors
    assert "sparse" in info.config.params.sparse_vectors
    hits = rag.retrieve("t", "serpentine coolant channels", top_k=3, hybrid=True)
    assert hits[0].patent_no == "US1"
    # Per-tenant isolation holds on v2 collections.
    assert rag.retrieve("other", "serpentine coolant channels", top_k=3, hybrid=True) == []


def test_qdrant_hybrid_respects_filters_and_prefer(qdrant_local):
    rag.index_patent("t", BATTERY, security_level="public")
    rag.index_patent("t", HEATSINK, security_level="public")
    hits = rag.retrieve("t", "fins heat sink", top_k=3, hybrid=True, prefer_patent_no="US1")
    assert hits[0].patent_no == "US1"
    only = rag._store.hybrid_search(
        "t",
        rag.embed("fins", "t", is_query=True),
        "fins",
        top_k=5,
        metadata_filter={"patent_no": "US2"},
    )
    assert only and {c.patent_no for c, _ in only} == {"US2"}


def test_qdrant_migrate_legacy(qdrant_local):
    store = rag._store
    qm = store._qm
    legacy = store._legacy_coll("t")
    store._client.create_collection(
        collection_name=legacy,
        vectors_config=qm.VectorParams(size=store._dim, distance=qm.Distance.COSINE),
    )
    chunks = rag.chunk_patent(BATTERY)
    store._client.upsert(
        collection_name=legacy,
        points=[
            qm.PointStruct(
                id=rag._chunk_point_id(c.chunk_id),
                vector=rag.embed(c.text, "t"),
                payload=store._payload(c),
            )
            for c in chunks
        ],
    )
    assert store.stats()["legacy_tenants_pending_migration"] == ["t"]
    moved = store.migrate_legacy("t", drop_legacy=True)
    assert moved == len(chunks)
    assert store.stats()["per_tenant_count"]["t"] == len(chunks)
    assert store.stats()["legacy_tenants_pending_migration"] == []
    assert rag.retrieve("t", "coolant channels", top_k=1, hybrid=True)[0].patent_no == "US1"


# ---------------------------------------------------------------------------
# Q39 public prior-art eval set
# ---------------------------------------------------------------------------

_CORPUS, _QUERIES = retrieval_eval.load_public_eval()
needs_public_set = pytest.mark.skipif(
    not _QUERIES, reason="data/eval/public_prior_art not built (scripts/build_public_eval_set.py)"
)


@needs_public_set
def test_public_set_is_non_circular_and_sized():
    assert len(_QUERIES) >= 30
    assert len(_CORPUS) >= 200
    corpus_ids = {d["patent_no"] for d in _CORPUS}
    for q in _QUERIES:
        # The patent under examination is never in its own search corpus …
        assert q["target_patent_no"] not in corpus_ids
        # … and every labelled reference is.
        assert set(q["relevant"]) <= corpus_ids
        assert len(q["relevant"]) >= 2


@needs_public_set
def test_public_eval_gate_and_gibberish_control():
    with rag.use_backends(embedding="lexical"):
        real = retrieval_eval.evaluate_public(k=5, hybrid=True)
        control = retrieval_eval.evaluate_public(
            k=5,
            hybrid=True,
            queries=retrieval_eval.gibberish_queries(_QUERIES),
            index=False,
        )
    assert real["hit@k"] >= retrieval_eval.PUBLIC_MIN_HIT_AT_5, real["hit@k"]
    assert real["mrr"] >= retrieval_eval.PUBLIC_MIN_MRR, real["mrr"]
    # Negative control: meaningless queries must NOT pass the gate (the old
    # circular eval scored gibberish HIGHER than real queries).
    assert control["hit@k"] < retrieval_eval.PUBLIC_MIN_HIT_AT_5
    assert control["hit@k"] <= real["hit@k"] / 3
