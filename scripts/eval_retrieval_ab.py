"""Side-by-side retrieval A/B on the PUBLIC prior-art eval set (Q9 / Q10 / Q11).

Runs the SAME queries + corpus through every requested configuration and
prints recall@5 / hit@5 / MRR / nDCG@5, plus a gibberish-query negative
control per configuration (it must collapse towards 0 — if it does not, the
configuration is not using the query).

    python scripts/eval_retrieval_ab.py                              # lexical only
    python scripts/eval_retrieval_ab.py --embeddings lexical,bge-m3,qwen3 \\
        --modes dense,hybrid --rerankers none,qwen3-4b
    python scripts/eval_retrieval_ab.py --store qdrant::memory:      # qdrant local mode
    python scripts/eval_retrieval_ab.py --store qdrant:http://localhost:6333

Heavy backends are optional: a configuration whose model / dependency is
missing is reported as SKIPPED with the reason, not a crash. On the RTX 3060
8GB box stop the local LLM (ollama stop) before GPU runs of qwen3 4B models,
or they fall back to CPU (slow but correct).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ai_engine import rag, retrieval_eval  # noqa: E402


def _run(embedding: str, mode: str, reranker: str, store: str, k: int) -> dict:
    corpus, queries = retrieval_eval.load_public_eval()
    hybrid = mode == "hybrid"
    with rag.use_backends(embedding=embedding, store=store, reranker=reranker):
        t0 = time.monotonic()
        real = retrieval_eval.evaluate_public(k=k, hybrid=hybrid, corpus=corpus, queries=queries)
        control = retrieval_eval.evaluate_public(
            k=k,
            hybrid=hybrid,
            corpus=corpus,
            queries=retrieval_eval.gibberish_queries(queries),
            index=False,
        )
        real["seconds"] = time.monotonic() - t0
    real["control_hit@k"] = control["hit@k"]
    real["control_mrr"] = control["mrr"]
    return real


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--embeddings", default="lexical")
    ap.add_argument("--modes", default="dense,hybrid")
    ap.add_argument("--rerankers", default="none")
    ap.add_argument("--store", default="memory")
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args()

    corpus, queries = retrieval_eval.load_public_eval()
    if not queries:
        print("public eval set missing — run scripts/build_public_eval_set.py first")
        return 2
    print(f"public prior-art eval: {len(queries)} queries, {len(corpus)} corpus docs, k={a.k}")
    header = (
        f"{'embedding':<10} {'mode':<7} {'reranker':<10} {'recall@k':>8} {'hit@k':>6} "
        f"{'MRR':>6} {'nDCG@k':>7} {'ctrl hit':>8} {'sec':>6}"
    )
    print(header)
    print("-" * len(header))
    for emb in a.embeddings.split(","):
        for mode in a.modes.split(","):
            for rr in a.rerankers.split(","):
                try:
                    r = _run(emb, mode, rr, a.store, a.k)
                except Exception as exc:  # noqa: BLE001 — optional heavy deps
                    print(f"{emb:<10} {mode:<7} {rr:<10} SKIPPED: {exc.__class__.__name__}: {exc}")
                    continue
                print(
                    f"{emb:<10} {mode:<7} {rr:<10} {r['recall@k']:>8.3f} {r['hit@k']:>6.3f} "
                    f"{r['mrr']:>6.3f} {r['ndcg@k']:>7.3f} {r['control_hit@k']:>8.3f} "
                    f"{r['seconds']:>6.1f}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
