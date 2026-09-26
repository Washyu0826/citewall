"""Re-index legacy Qdrant collections into the v2 hybrid schema (Q11).

v1: ``patentmind_<tenant>`` — one unnamed dense vector.
v2: ``patentmind_v2_<tenant>`` — named ``dense`` + IDF ``sparse`` vectors
    (native hybrid via the Query API).

The v2 code path never reads v1 collections, so after upgrading Qdrant
(v1.12.4 → v1.19.x) and the client, run this once per deployment:

    VECTOR_BACKEND=qdrant QDRANT_URL=http://localhost:6333 \\
        python scripts/qdrant_migrate_v2.py            # dry run: list tenants
    ... python scripts/qdrant_migrate_v2.py --apply    # re-index all
    ... python scripts/qdrant_migrate_v2.py --apply --tenant tenant_a --drop-legacy

Dense vectors are recomputed with the CURRENT embedder (EMBEDDING_BACKEND)
from the stored payload text; the legacy collection is kept unless
--drop-legacy (verify retrieval on v2 first). Back up the Qdrant volume
before running (ops/DR_RUNBOOK.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ai_engine import rag  # noqa: E402
from backend.shared.config import settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="actually re-index (default: dry run)")
    ap.add_argument("--tenant", action="append", help="limit to these tenants (repeatable)")
    ap.add_argument("--drop-legacy", action="store_true")
    a = ap.parse_args()

    if settings.VECTOR_BACKEND != "qdrant":
        print("VECTOR_BACKEND is not 'qdrant' — nothing to migrate.")
        return 2
    store = rag._store
    tenants = a.tenant or store.list_legacy_tenants()
    if not tenants:
        print("no legacy (v1) collections found.")
        return 0
    for t in tenants:
        if not a.apply:
            print(f"would migrate tenant {t!r}: patentmind_{t} → patentmind_v2_{t}")
            continue
        n = store.migrate_legacy(t, drop_legacy=a.drop_legacy)
        print(f"migrated tenant {t!r}: {n} points" + (" (legacy dropped)" if a.drop_legacy else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
