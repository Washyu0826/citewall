"""Q27 — per-data-subject erasure of the reversible PII map."""

from __future__ import annotations

import sqlite3

import pytest

from backend.gateway import backup, masking
from backend.shared import config


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    mapping_db = tmp_path / "mapping.db"
    monkeypatch.setattr(config, "MAPPING_DB_PATH", mapping_db)
    monkeypatch.setattr(config, "AUDIT_DB_PATH", tmp_path / "audit.db")
    monkeypatch.setattr(config, "PATENT_DB_PATH", tmp_path / "patent.db")
    monkeypatch.setattr(config, "AUDIT_ARCHIVE_DIR", tmp_path / "audit_archive")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    store = masking.MaskingStore(path=mapping_db)
    store.remember("tenant_a", "[PHONE_AAAA0001]", "0912-345-678", "phone_tw")
    store.remember("tenant_a", "[EMAIL_AAAA0002]", "Alice@Apex.com", "email")
    store.remember("tenant_a", "[PERSON_AAAA0003]", "陳小華", "ner_person")
    store.remember("tenant_b", "[PHONE_BBBB0001]", "0912-345-678", "phone_tw")
    return {"db": mapping_db, "store": store}


def _placeholders(db, tenant):
    conn = sqlite3.connect(db)
    try:
        return {
            r[0]
            for r in conn.execute("SELECT placeholder FROM mappings WHERE tenant_id=?", (tenant,))
        }
    finally:
        conn.close()


def test_subject_hmac_is_keyed_and_normalised():
    a = masking.subject_hmac("tenant_a", "0912-345-678")
    assert a == masking.subject_hmac("tenant_a", "0912 345 678")
    assert a == masking.subject_hmac("tenant_a", "０９１２３４５６７８")  # fullwidth
    assert a != masking.subject_hmac("tenant_b", "0912-345-678")
    assert "0912" not in a


def test_no_plaintext_in_lookup_column(stores):
    conn = sqlite3.connect(stores["db"])
    try:
        rows = conn.execute("SELECT original, subject_hmac FROM mappings").fetchall()
    finally:
        conn.close()
    for original, h in rows:
        assert "0912" not in original and "0912" not in h
        assert len(h) == 64


def test_erase_subject_deletes_only_that_subject_in_that_tenant(stores):
    result = backup.erase_subject("tenant_a", ["0912 345 678", "alice@apex.com"])
    assert result["erased_mapping_entries"] == 2
    assert result["rules_matched"] == ["email", "phone_tw"]
    assert _placeholders(stores["db"], "tenant_a") == {"[PERSON_AAAA0003]"}
    # the same phone number under another tenant is a different subject record
    assert _placeholders(stores["db"], "tenant_b") == {"[PHONE_BBBB0001]"}
    # placeholder is now irreversible
    assert masking.MaskingStore(stores["db"]).get_original("tenant_a", "[PHONE_AAAA0001]") is None


def test_erase_subject_dry_run(stores):
    result = backup.erase_subject("tenant_a", ["陳小華"], dry_run=True)
    assert result["matched_mapping_entries"] == 1
    assert result["erased_mapping_entries"] == 0
    assert result["note"].startswith("DRY RUN")
    assert "[PERSON_AAAA0003]" in _placeholders(stores["db"], "tenant_a")


def test_erase_subject_no_match_is_honest(stores):
    result = backup.erase_subject("tenant_a", ["nobody@nowhere.test"])
    assert result["erased_mapping_entries"] == 0
    assert result["note"].startswith("NOTHING ERASED")


def test_erase_subject_reports_backups_still_holding_subject(stores):
    backup.snapshot()
    result = backup.erase_subject("tenant_a", ["0912-345-678"])
    assert result["erased_mapping_entries"] == 1
    assert len(result["backups_with_subject"]) == 1
    assert result["backups_with_subject"][0]["rows"] == 1
    assert any("backup snapshot" in n for n in result["not_covered"])


def test_erase_subject_requires_identifier(stores):
    with pytest.raises(ValueError):
        backup.erase_subject("tenant_a", ["  "])


def test_migration_backfills_legacy_db_and_encrypts_plaintext(tmp_path):
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE mappings (tenant_id TEXT NOT NULL, placeholder TEXT NOT NULL, "
        "original TEXT NOT NULL, rule_id TEXT NOT NULL, "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (tenant_id, placeholder))"
    )
    token = masking._tenant_fernet("tenant_a").encrypt(b"bob@beta.com").decode()
    conn.execute(
        "INSERT INTO mappings(tenant_id, placeholder, original, rule_id) VALUES (?,?,?,?)",
        ("tenant_a", "[EMAIL_00000001]", token, "email"),
    )
    conn.execute(  # pre-encryption era plaintext row
        "INSERT INTO mappings(tenant_id, placeholder, original, rule_id) VALUES (?,?,?,?)",
        ("tenant_a", "[PHONE_00000002]", "0912345678", "phone_tw"),
    )
    conn.commit()

    assert masking.migrate_mapping_db(conn) == 2
    assert masking.migrate_mapping_db(conn) == 0  # idempotent
    rows = dict(conn.execute("SELECT placeholder, original FROM mappings").fetchall())
    conn.close()
    assert "0912345678" not in rows["[PHONE_00000002]"]  # re-encrypted at rest
    store = masking.MaskingStore(db)
    assert store.get_original("tenant_a", "[PHONE_00000002]") == "0912345678"
    assert store.get_original("tenant_a", "[EMAIL_00000001]") == "bob@beta.com"


def test_cli_erase_subject(stores, capsys):
    rc = backup._main(
        ["backup", "erase-subject", "tenant_a", "--value", "0912-345-678", "--dry-run"]
    )
    assert rc == 0
    assert '"matched_mapping_entries": 1' in capsys.readouterr().out
    assert backup._main(["backup", "erase-subject", "tenant_a"]) == 2
