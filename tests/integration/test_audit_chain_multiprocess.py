"""H-10: the audit chain must not fork when several PROCESSES write at once.

Several gateway replicas share one audit store. The writer's in-process RLock
cannot serialise them, so read-tail → insert must be atomic in the database.
If two writers chain off the same tail, two rows share a prev_row_hash and
verify_global_chain reports the fork as tampering.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from backend.gateway import audit

WRITERS = 4
ROWS_PER_WRITER = 40
REPO_ROOT = Path(__file__).resolve().parents[2]

_CHILD = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path

    db, go, n, name = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4]

    # Point the module-level default writer at a scratch file BEFORE importing
    # audit, so the child never opens the repo's real data/audit.db.
    import backend.shared.config as config
    config.AUDIT_DB_PATH = db.with_name(f"unused-{name}.db")

    from backend.gateway import audit
    from backend.shared.models import User, UserRole

    user = User(user_id=name, tenant_id="tenant_a", role=UserRole.ATTORNEY,
                display_name=name, daily_token_quota=10_000)
    w = audit.AuditWriter(path=db)
    while not go.exists():
        time.sleep(0.005)
    for i in range(n):
        w.write(user=user, case_id=f"CASE-{name}-{i}", endpoint="/t",
                request_payload={"i": i}, response_payload={"ok": True},
                masked_rules=[], model_used="mock", prompt_tokens=1,
                completion_tokens=1, latency_ms=1, policy_decisions={})
    """
)


def test_concurrent_processes_keep_one_linear_chain(tmp_path):
    db = tmp_path / "audit.db"
    audit.AuditWriter(path=db).close()  # create schema before the race
    go = tmp_path / "go"

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _CHILD, str(db), str(go), str(ROWS_PER_WRITER), f"w{i}"],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for i in range(WRITERS)
    ]
    time.sleep(1.0)  # let every child reach the start line
    go.touch()
    for p in procs:
        _, err = p.communicate(timeout=120)
        assert p.returncode == 0, err.decode("utf-8", "replace")

    w = audit.AuditWriter(path=db)
    rows = w.read_all_rows()
    assert len(rows) == WRITERS * ROWS_PER_WRITER

    prevs = [r["prev_row_hash"] for r in rows]
    assert len(set(prevs)) == len(prevs), "two rows chained off the same tail (fork)"
    for earlier, later in zip(rows, rows[1:], strict=False):
        assert later["prev_row_hash"] == earlier["row_hash"]

    result = w.verify_global_chain()
    assert result["broken"] == []
    assert result["verified"] == WRITERS * ROWS_PER_WRITER
