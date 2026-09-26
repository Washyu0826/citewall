"""Security phase 2 (2026-09-25): Q22 case registry, Q23 magic-link email,
Q24 demo passwords mock-only, Q26 HMAC audit chain (v2) + migration."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from concurrent.futures import Future

import pytest

from backend.gateway import audit, mailer
from backend.shared import case_registry
from backend.shared.config import settings
from backend.shared.models import User, UserRole


# ---------------------------------------------------------------------------
# Q22 — case registry (fail-closed)
# ---------------------------------------------------------------------------
@pytest.fixture()
def registry(tmp_path, monkeypatch):
    path = tmp_path / "case_registry.json"
    path.write_text(
        json.dumps(
            {
                "cases": {"CASE-P-1": "public", "CASE-C-1": "confidential"},
                "patterns": {"CASE-DEMO-*": "public"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(path))
    return path


def test_registry_resolution(registry):
    lvl = case_registry.security_level_for_case
    assert lvl("CASE-P-1") == "public"
    assert lvl("CASE-C-1") == "confidential"
    assert lvl("CASE-DEMO-042") == "public"  # glob pattern
    assert lvl("CASE-UNKNOWN-9") == "confidential"  # unregistered => fail-closed
    assert lvl("") == "confidential"
    assert lvl(None) == "confidential"


def test_conf_suffix_always_confidential(registry):
    # A registry entry can never loosen the legacy -CONF signal.
    registry.write_text(json.dumps({"cases": {"CASE-P-1-CONF": "public"}}), encoding="utf-8")
    os.utime(registry, (1, 1))  # force a distinct mtime for the reload
    assert case_registry.security_level_for_case("CASE-P-1-CONF") == "confidential"


def test_missing_or_broken_registry_is_confidential(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(tmp_path / "nope.json"))
    assert case_registry.security_level_for_case("CASE-2025-001") == "confidential"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(bad))
    assert case_registry.security_level_for_case("CASE-2025-001") == "confidential"


def test_registry_reloads_on_change(registry):
    assert case_registry.security_level_for_case("CASE-NEW") == "confidential"
    registry.write_text(json.dumps({"cases": {"CASE-NEW": "public"}}), encoding="utf-8")
    os.utime(registry, (2, 2))
    assert case_registry.security_level_for_case("CASE-NEW") == "public"


def test_shipped_registry_marks_demo_cases_public():
    # The repo's data/case_registry.json keeps the demo flows on cloud models.
    for cid in ("CASE-2025-001", "CASE-2025-002", "CASE-2025-003", "CASE-DEMO-001"):
        assert case_registry.security_level_for_case(cid) == "public", cid


def test_upload_blocks_unregistered_case(gateway_client, alice_token, tmp_path, monkeypatch):
    # alice's ACL includes CASE-2025-002; with a registry that omits it the
    # case is confidential => the cloud-OCR upload path must refuse it.
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"cases": {"CASE-2025-001": "public"}}), encoding="utf-8")
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(reg))
    resp = gateway_client.post(
        "/v1/oa/upload",
        headers={"Authorization": f"Bearer {alice_token}", "X-Case-Id": "CASE-2025-002"},
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
    )
    assert resp.status_code == 403, resp.text
    assert "Confidential" in resp.text


# ---------------------------------------------------------------------------
# Q24 — demo passwords only in mock mode
# ---------------------------------------------------------------------------
def _login(client, password="demo-alice"):
    return client.post("/v1/auth/login", json={"user_id": "alice", "password": password})


def test_demo_password_works_in_mock(gateway_client):
    assert _login(gateway_client).status_code == 200


def test_demo_password_refused_outside_mock(gateway_client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    monkeypatch.setattr(settings, "DEMO_PASSWORDS_ENABLED", None)
    assert _login(gateway_client).status_code == 401


def test_demo_password_explicit_override(gateway_client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    monkeypatch.setattr(settings, "DEMO_PASSWORDS_ENABLED", True)
    assert _login(gateway_client).status_code == 200
    monkeypatch.setattr(settings, "LLM_MODE", "mock")
    monkeypatch.setattr(settings, "DEMO_PASSWORDS_ENABLED", False)
    assert _login(gateway_client).status_code == 401


# ---------------------------------------------------------------------------
# Q23 — magic-link email
# ---------------------------------------------------------------------------
class _FakeSMTP:
    sent: list = []
    instances: list = []

    def __init__(self, host, port, timeout=None, **kw):
        self.host, self.port = host, port
        self.calls: list[str] = []
        _FakeSMTP.instances.append(self)

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(f"login:{user}")

    def send_message(self, msg):
        _FakeSMTP.sent.append(msg)

    def quit(self):
        self.calls.append("quit")

    def close(self):
        pass


class _SyncExecutor:
    def submit(self, fn, *args):
        fut: Future = Future()
        fut.set_result(fn(*args))
        return fut


@pytest.fixture()
def fake_smtp(monkeypatch):
    _FakeSMTP.sent = []
    _FakeSMTP.instances = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(mailer, "_executor", _SyncExecutor())
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_FROM", "noreply@example.com")
    monkeypatch.setattr(settings, "SMTP_USER", "mailer")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "pw")
    monkeypatch.setattr(settings, "SMTP_SECURITY", "starttls")
    monkeypatch.setattr(settings, "MAGIC_LINK_BASE_URL", "https://app.example.com/login")
    return _FakeSMTP


def test_magic_link_emails_known_user(gateway_client, fake_smtp, monkeypatch):
    monkeypatch.setattr(settings, "MAGIC_LINK_RETURN_TOKEN", False)
    resp = gateway_client.post("/v1/auth/magic/request", json={"user_id": "alice"})
    assert resp.status_code == 200
    assert resp.json()["magic_token"] is None  # production shape: token only by email
    assert len(fake_smtp.sent) == 1
    msg = fake_smtp.sent[0]
    assert msg["To"] == "alice@example.com"
    body = msg.get_content()
    assert "https://app.example.com/login#token=" in body
    assert fake_smtp.instances[0].calls[:2] == ["starttls", "login:mailer"]


def test_magic_link_unknown_user_sends_nothing_same_response(
    gateway_client, fake_smtp, monkeypatch
):
    monkeypatch.setattr(settings, "MAGIC_LINK_RETURN_TOKEN", False)
    known = gateway_client.post("/v1/auth/magic/request", json={"user_id": "alice"}).json()
    fake_smtp.sent.clear()
    unknown = gateway_client.post("/v1/auth/magic/request", json={"user_id": "nobody"}).json()
    assert fake_smtp.sent == []
    assert known == unknown  # no enumeration signal


def test_magic_link_smtp_unconfigured_is_generic(gateway_client, fake_smtp, monkeypatch):
    monkeypatch.setattr(settings, "MAGIC_LINK_RETURN_TOKEN", False)
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    resp = gateway_client.post("/v1/auth/magic/request", json={"user_id": "alice"})
    assert resp.status_code == 200
    assert fake_smtp.sent == []


def test_emailed_token_can_be_consumed(gateway_client, fake_smtp, monkeypatch):
    monkeypatch.setattr(settings, "MAGIC_LINK_RETURN_TOKEN", False)
    gateway_client.post("/v1/auth/magic/request", json={"user_id": "alice"})
    link = fake_smtp.sent[0].get_content().split("#token=", 1)[1].split()[0]
    resp = gateway_client.post("/v1/auth/magic/consume", json={"token": link})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_id"] == "alice"


# ---------------------------------------------------------------------------
# Q26 — HMAC v2 audit chain
# ---------------------------------------------------------------------------
_USER = User(
    user_id="u1",
    tenant_id="tenant_a",
    role=UserRole.ATTORNEY,
    display_name="t",
    daily_token_quota=10_000,
)


def _write(w, i=0, policy=None):
    return w.write(
        user=_USER,
        case_id=f"CASE-{i}",
        endpoint="/t",
        request_payload={"i": i},
        response_payload={"ok": True},
        masked_rules=["EMAIL"],
        model_used="mock",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=3,
        policy_decisions=policy or {"attorney_signoff": False},
    )


def _raw(db):
    conn = sqlite3.connect(db)
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    return conn


def test_v2_rows_verify(tmp_path):
    w = audit.AuditWriter(path=tmp_path / "a.db")
    ids = [_write(w, i) for i in range(3)]
    assert w.verify_chain("tenant_a") == {
        "verified": 3,
        "broken": [],
        "unverifiable": [],
        "tenant": "tenant_a",
    }
    versions = [r["hash_version"] for r in w.read_all_rows()]
    assert versions == [audit.HASH_V2] * 3
    assert w.verify_global_chain()["broken"] == []
    assert len(ids) == 3


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("policy_decisions", '{"attorney_signoff": true}'),
        ("model_used", "claude-opus-forged"),
        ("prompt_tokens", 1),
        ("masked_field_rules", "[]"),
        ("latency_ms", 999),
    ],
)
def test_v2_detects_tampering_of_non_chain_fields(tmp_path, column, value):
    db = tmp_path / "a.db"
    w = audit.AuditWriter(path=db)
    ids = [_write(w, i) for i in range(3)]
    conn = _raw(db)
    conn.execute(f"UPDATE audit SET {column} = ? WHERE audit_id = ?", (value, ids[1]))  # noqa: S608
    conn.commit()
    conn.close()
    assert ids[1] in w.verify_chain("tenant_a")["broken"]
    assert ("tenant_a", ids[1]) in w.verify_global_chain()["broken"]


def test_v2_hash_needs_the_key(tmp_path, monkeypatch):
    # An attacker recomputing the legacy sha256 (or an HMAC under another key)
    # for a tampered row still fails verification.
    db = tmp_path / "a.db"
    w = audit.AuditWriter(path=db)
    ids = [_write(w, i) for i in range(2)]
    row = next(r for r in w.read_all_rows() if r["audit_id"] == ids[1])
    row["policy_decisions"] = '{"attorney_signoff": true}'
    monkeypatch.setattr(settings, "AUDIT_HMAC_KEY", "attacker-guess")
    forged = audit.AuditWriter.expected_row_hash(row)
    monkeypatch.setattr(settings, "AUDIT_HMAC_KEY", "")
    conn = _raw(db)
    conn.execute(
        "UPDATE audit SET policy_decisions = ?, row_hash = ? WHERE audit_id = ?",
        (row["policy_decisions"], forged, ids[1]),
    )
    conn.commit()
    conn.close()
    assert ids[1] in w.verify_chain("tenant_a")["broken"]


_LEGACY_DDL = """
CREATE TABLE audit (
    audit_id TEXT PRIMARY KEY, timestamp_utc TEXT NOT NULL, timestamp_local TEXT NOT NULL,
    user_id TEXT NOT NULL, tenant_id TEXT NOT NULL, case_id TEXT, endpoint TEXT NOT NULL,
    request_hash TEXT NOT NULL, response_hash TEXT, masked_field_rules TEXT NOT NULL,
    model_used TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, latency_ms INTEGER,
    policy_decisions TEXT NOT NULL, prev_row_hash TEXT, row_hash TEXT NOT NULL
);
"""


def _legacy_row(prev: str, i: int) -> tuple:
    aid = str(uuid.uuid4())
    row = {
        "audit_id": aid,
        "timestamp_utc": f"2026-01-01T00:00:0{i}+00:00",
        "user_id": "u1",
        "tenant_id": "tenant_a",
        "case_id": "CASE-L",
        "endpoint": "/legacy",
        "request_hash": "rq",
        "response_hash": "rp",
        "prev_row_hash": prev,
    }
    h = audit.AuditWriter.expected_row_hash({**row, "hash_version": None})
    return (
        aid,
        row["timestamp_utc"],
        "local",
        "u1",
        "tenant_a",
        "CASE-L",
        "/legacy",
        "rq",
        "rp",
        "[]",
        "mock",
        0,
        0,
        0,
        "{}",
        prev,
        h,
    )


def test_legacy_v1_db_migrates_and_still_verifies(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(_LEGACY_DDL)
    prev = ""
    for i in range(2):
        vals = _legacy_row(prev, i)
        conn.execute(f"INSERT INTO audit VALUES ({','.join('?' * 17)})", vals)
        prev = vals[-1]
    conn.commit()
    conn.close()

    # Read-only archival read works on the unmigrated file (NULL version).
    w = audit.AuditWriter(path=db)  # opening migrates (ADD COLUMN hash_version)
    _write(w, 9)  # a new v2 row chains off the last v1 row
    result = w.verify_chain("tenant_a")
    assert result["broken"] == [], result
    assert result["verified"] == 3
    versions = [r["hash_version"] for r in w.read_all_rows()]
    assert versions == [None, None, audit.HASH_V2]


def test_v1_row_after_v2_is_a_downgrade(tmp_path):
    db = tmp_path / "a.db"
    w = audit.AuditWriter(path=db)
    _write(w, 0)
    last = w.read_all_rows()[-1]["row_hash"]
    vals = _legacy_row(last, 1)  # a CORRECT legacy sha256 — but after v2
    with w._lock:
        w._conn.execute(
            f"INSERT INTO audit (audit_id, timestamp_utc, timestamp_local, user_id, tenant_id,"
            f" case_id, endpoint, request_hash, response_hash, masked_field_rules, model_used,"
            f" prompt_tokens, completion_tokens, latency_ms, policy_decisions, prev_row_hash,"
            f" row_hash) VALUES ({','.join('?' * 17)})",
            vals,
        )
        w._conn.commit()
    assert vals[0] in w.verify_chain("tenant_a")["broken"]


def test_archive_seals_v2_fields(tmp_path, monkeypatch):
    from backend.gateway import audit_archive
    from backend.shared import config

    db = tmp_path / "a.db"
    w = audit.AuditWriter(path=db)
    _write(w, 0, policy={"attorney_signoff": True})
    monkeypatch.setattr(config, "AUDIT_DB_PATH", db)
    rows = audit.read_live_rows()
    assert rows[0]["hash_version"] == audit.HASH_V2
    assert json.loads(rows[0]["policy_decisions"]) == {"attorney_signoff": True}
    assert hasattr(audit_archive, "seal_next_segment")
