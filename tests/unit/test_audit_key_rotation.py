"""Q21 — audit HMAC key rotation (hash_key_id + keyring)."""

from __future__ import annotations

import sqlite3

import pytest

from backend.gateway import audit, audit_archive
from backend.shared.config import settings
from backend.shared.models import User, UserRole

_USER = User(
    user_id="u1",
    tenant_id="tenant_a",
    role=UserRole.ATTORNEY,
    display_name="t",
    daily_token_quota=10_000,
)


def _write(w, i=0):
    return w.write(
        user=_USER,
        case_id=f"CASE-{i}",
        endpoint="/t",
        request_payload={"i": i},
        response_payload={"ok": True},
        masked_rules=[],
        model_used="mock",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1,
        policy_decisions={"attorney_signoff": False},
    )


@pytest.fixture
def ring(monkeypatch):
    """Helper to set the keyring for the duration of a test."""

    def _set(keys: str, active: str = "", single: str = ""):
        monkeypatch.setattr(settings, "AUDIT_HMAC_KEYS", keys)
        monkeypatch.setattr(settings, "AUDIT_HMAC_ACTIVE_KID", active)
        monkeypatch.setattr(settings, "AUDIT_HMAC_KEY", single)

    return _set


def _kids(w):
    return [r["hash_key_id"] for r in w.read_all_rows()]


def test_rows_record_active_kid(tmp_path, ring):
    ring("k1:alpha,k2:beta", active="k2")
    w = audit.AuditWriter(path=tmp_path / "a.db")
    _write(w)
    assert _kids(w) == ["k2"]
    assert w.verify_chain("tenant_a")["broken"] == []


def test_single_key_is_kid_k1(tmp_path, ring):
    ring("", single="legacy-secret")
    w = audit.AuditWriter(path=tmp_path / "a.db")
    _write(w)
    assert _kids(w) == ["k1"]


def test_rotate_mid_chain_whole_chain_verifies(tmp_path, ring):
    db = tmp_path / "a.db"
    ring("", single="old-secret")  # pre-rotation deployment: AUDIT_HMAC_KEY only
    w = audit.AuditWriter(path=db)
    _write(w, 0)
    _write(w, 1)
    # Rotate: keep the old key in the ring as k1, sign new rows with k2.
    ring("k1:old-secret,k2:new-secret", active="k2")
    _write(w, 2)
    _write(w, 3)
    assert _kids(w) == ["k1", "k1", "k2", "k2"]
    res = w.verify_chain("tenant_a")
    assert res["verified"] == 4 and res["broken"] == [] and res["unverifiable"] == []
    glob = w.verify_global_chain()
    assert glob["broken"] == [] and glob["unverifiable"] == []


def test_missing_old_key_is_flagged_unverifiable(tmp_path, ring):
    db = tmp_path / "a.db"
    ring("k1:old-secret,k2:new-secret", active="k1")
    w = audit.AuditWriter(path=db)
    old_ids = [_write(w, 0), _write(w, 1)]
    ring("k1:old-secret,k2:new-secret", active="k2")
    _write(w, 2)
    # Operator drops k1 from the ring by mistake.
    ring("k2:new-secret", active="k2")
    res = w.verify_chain("tenant_a")
    assert res["unverifiable"] == old_ids
    assert set(old_ids) <= set(res["broken"])  # fail-closed: never "verified"
    assert res["verified"] == 1
    glob = w.verify_global_chain()
    assert [aid for _t, aid in glob["unverifiable"]] == old_ids


def test_wrong_key_under_same_kid_is_broken_not_unverifiable(tmp_path, ring):
    db = tmp_path / "a.db"
    ring("k1:real", active="k1")
    w = audit.AuditWriter(path=db)
    aid = _write(w)
    ring("k1:WRONG", active="k1")
    res = w.verify_chain("tenant_a")
    assert res["broken"] == [aid] and res["unverifiable"] == []


def test_relabelling_kid_does_not_verify(tmp_path, ring):
    """A DB-write attacker re-pointing a forged row at another ring key gains
    nothing: the HMAC is checked under the key the label names."""
    db = tmp_path / "a.db"
    ring("k1:a,k2:b", active="k1")
    w = audit.AuditWriter(path=db)
    aid = _write(w)
    conn = sqlite3.connect(db)
    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("UPDATE audit SET hash_key_id = 'k2' WHERE audit_id = ?", (aid,))
    conn.commit()
    conn.close()
    assert w.verify_chain("tenant_a")["broken"] == [aid]


def test_pre_rotation_v2_rows_null_kid_verify_with_legacy_key(tmp_path, ring):
    """A v2 row written before hash_key_id existed (NULL) verifies with k1."""
    db = tmp_path / "a.db"
    ring("", single="legacy")
    w = audit.AuditWriter(path=db)
    aid = _write(w)
    conn = sqlite3.connect(db)
    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("UPDATE audit SET hash_key_id = NULL WHERE audit_id = ?", (aid,))
    conn.commit()
    conn.close()
    ring("k1:legacy,k2:new", active="k2")
    assert w.verify_chain("tenant_a")["broken"] == []


def test_migration_adds_column_idempotently(tmp_path, ring):
    ring("", single="s")
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE audit (audit_id TEXT PRIMARY KEY, timestamp_utc TEXT NOT NULL, "
        "timestamp_local TEXT NOT NULL, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL, "
        "case_id TEXT, endpoint TEXT NOT NULL, request_hash TEXT NOT NULL, "
        "response_hash TEXT, masked_field_rules TEXT NOT NULL, model_used TEXT, "
        "prompt_tokens INTEGER, completion_tokens INTEGER, latency_ms INTEGER, "
        "policy_decisions TEXT NOT NULL, prev_row_hash TEXT, row_hash TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()
    audit.AuditWriter(path=db).close()
    audit.AuditWriter(path=db).close()  # second open: no error
    cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(audit)")]
    assert "hash_version" in cols and "hash_key_id" in cols


def test_archive_seals_kid(tmp_path, ring, monkeypatch):
    from backend.shared import config

    ring("k1:a,k2:b", active="k2")
    db = tmp_path / "a.db"
    arc = tmp_path / "archive"
    monkeypatch.setattr(config, "AUDIT_DB_PATH", db)
    monkeypatch.setattr(config, "AUDIT_ARCHIVE_DIR", arc)
    w = audit.AuditWriter(path=db)
    _write(w)
    w.close()
    audit_archive.seal_next_segment(now_iso="2026-09-26T00:00:00+00:00")
    import json

    records = [
        json.loads(line)
        for seg in sorted(arc.glob("*.jsonl"))
        for line in seg.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records and records[0]["hash_key_id"] == "k2"


def test_boot_guard_rejects_active_kid_not_in_ring(monkeypatch):
    from backend.shared import config

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(settings, "LLM_MODE", "local")
    monkeypatch.setattr(settings, "AUDIT_HMAC_KEYS", "k1:a")
    monkeypatch.setattr(settings, "AUDIT_HMAC_ACTIVE_KID", "k9")
    with pytest.raises(RuntimeError, match="not in"):
        config._validate_audit_hmac_config()
    monkeypatch.setattr(settings, "AUDIT_HMAC_KEYS", "garbage")
    with pytest.raises(RuntimeError, match="kid:secret"):
        config._validate_audit_hmac_config()
    monkeypatch.setattr(settings, "AUDIT_HMAC_KEYS", "k1:a,k2:b")
    monkeypatch.setattr(settings, "AUDIT_HMAC_ACTIVE_KID", "k2")
    config._validate_audit_hmac_config()  # ok
