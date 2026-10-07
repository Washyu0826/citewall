"""Q13 — WORM archive on a real S3 Object Lock target (``ARCHIVE_BACKEND=s3``).

Runs against the compose RustFS (S3 API on :19000 — ``docker compose up -d
rustfs``; MinIO until it left Docker Hub, FAILURE_LOG E-4). Mirrors the
Qdrant/Postgres gating pattern: every test skips cleanly when the store (or
boto3) is absent, so CI without containers stays green — EXCEPT when
``ARCHIVE_S3_REQUIRED=1`` (the CI services job): there a missing store is a
failure, so a store that never started cannot turn CI green.

Each test creates its OWN bucket with Object Lock enabled (versioning
implied), uses GOVERNANCE mode with a 1-day retention so teardown can clean up
via the governance bypass (COMPLIANCE objects would be undeletable until
expiry — the production posture, but hostile to a dev store).

What must hold:

  * sealing uploads segment + manifest objects carrying Object Lock retention;
  * ``verify_archive`` pulls everything back from the bucket and re-verifies
    the Merkle/segment chain + the live-DB cross-check;
  * WORM semantics — deleting a sealed object VERSION without the governance
    bypass is refused by the store, and an overwrite only ADDS a version (the
    sealed bytes stay retrievable) while verify flags the tampered latest.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.gateway import audit, audit_archive
from backend.shared import config
from backend.shared.config import settings
from backend.shared.models import User, UserRole

# Where the store is required (CI), a missing client must fail, not skip.
if os.getenv("ARCHIVE_S3_REQUIRED") == "1":
    import boto3
else:
    boto3 = pytest.importorskip("boto3")

from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.ARCHIVE_S3_ENDPOINT,
        aws_access_key_id=settings.ARCHIVE_S3_ACCESS_KEY,
        aws_secret_access_key=settings.ARCHIVE_S3_SECRET_KEY,
        region_name=settings.ARCHIVE_S3_REGION,
        config=Config(connect_timeout=2, read_timeout=10, retries={"max_attempts": 1}),
    )


def _store_or_skip():
    client = _client()
    try:
        client.list_buckets()
    except Exception as exc:  # pragma: no cover - env-dependent
        msg = f"S3 store not reachable at {settings.ARCHIVE_S3_ENDPOINT}: {exc}"
        if os.getenv("ARCHIVE_S3_REQUIRED") == "1":
            pytest.fail(msg)
        pytest.skip(msg)
    return client


def _nuke_bucket(client, bucket: str) -> None:
    """Best-effort teardown: remove every version (governance bypass) + bucket."""
    try:
        paginator = client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket):
            for v in page.get("Versions", []) + page.get("DeleteMarkers", []):
                client.delete_object(
                    Bucket=bucket,
                    Key=v["Key"],
                    VersionId=v["VersionId"],
                    BypassGovernanceRetention=True,
                )
        client.delete_bucket(Bucket=bucket)
    except Exception:  # pragma: no cover - teardown must never fail the test
        pass


@pytest.fixture()
def s3_archive(tmp_path, monkeypatch):
    """Fresh tmp audit DB (sqlite) + fresh Object-Lock bucket, archiver in s3 mode."""
    client = _store_or_skip()

    bucket = f"pm-worm-test-{uuid.uuid4().hex[:10]}"
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)

    db_path = tmp_path / "audit.db"
    monkeypatch.setattr(config, "AUDIT_DB_PATH", db_path)
    monkeypatch.setattr(config.settings, "AUDIT_BACKEND", "sqlite")
    monkeypatch.setattr(config.settings, "ARCHIVE_BACKEND", "s3")
    monkeypatch.setattr(config.settings, "ARCHIVE_S3_BUCKET", bucket)
    monkeypatch.setattr(config.settings, "ARCHIVE_S3_RETENTION_MODE", "GOVERNANCE")
    monkeypatch.setattr(config.settings, "ARCHIVE_S3_RETENTION_DAYS", 1)

    writer = audit.AuditWriter(path=db_path)
    yield {"writer": writer, "client": client, "bucket": bucket}
    writer.close()
    _nuke_bucket(client, bucket)


def _write_rows(writer, n: int, start: int = 0) -> list[str]:
    user = User(
        user_id="alice",
        tenant_id="tenant_a",
        role=UserRole.ATTORNEY,
        display_name="Alice",
    )
    ids = []
    for i in range(start, start + n):
        ids.append(
            writer.write(
                user=user,
                case_id=f"case-{i}",
                endpoint="/v1/analyze",
                request_payload={"q": i},
                response_payload={"a": i},
                masked_rules=["pii.email"],
                model_used="mock",
                prompt_tokens=10,
                completion_tokens=20,
                latency_ms=5,
                policy_decisions={"redacted": True},
            )
        )
    return ids


# ---------------------------------------------------------------------------
# 1. Seal → objects exist in the bucket WITH Object Lock retention.
# ---------------------------------------------------------------------------
def test_seal_uploads_locked_objects(s3_archive):
    _write_rows(s3_archive["writer"], 3)
    result = audit_archive.seal_next_segment(now_iso="2026-06-12T00:00:00+00:00")
    assert result["sealed"] is True
    assert result["segment_file"] == f"s3://{s3_archive['bucket']}/segment-0001.jsonl"

    head = s3_archive["client"].head_object(
        Bucket=s3_archive["bucket"], Key="segment-0001.jsonl"
    )
    assert head["ObjectLockMode"] == "GOVERNANCE"
    retain = head["ObjectLockRetainUntilDate"]
    assert retain > datetime.now(UTC)

    man_head = s3_archive["client"].head_object(
        Bucket=s3_archive["bucket"], Key="segment-0001.manifest.json"
    )
    assert man_head["ObjectLockMode"] == "GOVERNANCE"

    st = audit_archive.archive_status()
    assert st["archived_rows"] == 3
    assert st["rows_pending"] == 0
    assert st["segment_count"] == 1
    assert st["archive_dir"] == f"s3://{s3_archive['bucket']}"


# ---------------------------------------------------------------------------
# 2. verify_archive round-trips from the bucket; multi-segment chain holds.
# ---------------------------------------------------------------------------
def test_verify_ok_across_two_segments(s3_archive):
    _write_rows(s3_archive["writer"], 3)
    r1 = audit_archive.seal_next_segment()
    _write_rows(s3_archive["writer"], 2, start=50)
    r2 = audit_archive.seal_next_segment()
    assert r2["prev_root"] == r1["merkle_root"]
    assert r2["row_offset_start"] == 3

    rep = audit_archive.verify_archive()
    assert rep["ok"] is True, rep["anomalies"]
    assert rep["segments"] == 2
    assert rep["rows_archived"] == 5


# ---------------------------------------------------------------------------
# 3. Idempotency + refuse-to-overwrite guard.
# ---------------------------------------------------------------------------
def test_reseal_noop_and_existing_key_refused(s3_archive):
    _write_rows(s3_archive["writer"], 2)
    assert audit_archive.seal_next_segment()["sealed"] is True
    second = audit_archive.seal_next_segment()
    assert second["sealed"] is False
    assert second["reason"] == "no_pending_rows"

    # Pre-create the NEXT segment key (a crashed partial seal / malicious
    # pre-creation) — seal must refuse, not overwrite.
    _write_rows(s3_archive["writer"], 2, start=100)
    s3_archive["client"].put_object(
        Bucket=s3_archive["bucket"], Key="segment-0002.jsonl", Body=b"garbage\n"
    )
    refused = audit_archive.seal_next_segment()
    assert refused["sealed"] is False
    assert refused["reason"] == "segment_already_exists"


# ---------------------------------------------------------------------------
# 4. WORM semantics — the store itself refuses deleting a sealed version.
# ---------------------------------------------------------------------------
def test_sealed_version_delete_is_refused_without_bypass(s3_archive):
    _write_rows(s3_archive["writer"], 2)
    audit_archive.seal_next_segment()

    client, bucket = s3_archive["client"], s3_archive["bucket"]
    head = client.head_object(Bucket=bucket, Key="segment-0001.jsonl")
    version_id = head["VersionId"]

    with pytest.raises(ClientError) as exc:
        client.delete_object(Bucket=bucket, Key="segment-0001.jsonl", VersionId=version_id)
    assert exc.value.response["Error"]["Code"] in ("AccessDenied", "InvalidRequest")

    # The sealed bytes are still there.
    obj = client.get_object(Bucket=bucket, Key="segment-0001.jsonl", VersionId=version_id)
    assert b"row_hash" in obj["Body"].read()


# ---------------------------------------------------------------------------
# 5. Overwrite only ADDS a version; verify flags the tampered latest and the
#    original sealed version remains retrievable as evidence.
# ---------------------------------------------------------------------------
def test_overwrite_leaves_version_and_verify_detects(s3_archive):
    _write_rows(s3_archive["writer"], 2)
    audit_archive.seal_next_segment()
    assert audit_archive.verify_archive()["ok"] is True

    client, bucket = s3_archive["client"], s3_archive["bucket"]
    original = client.get_object(Bucket=bucket, Key="segment-0001.jsonl")
    original_version = original["VersionId"]
    original_body = original["Body"].read()

    # Attacker overwrites the sealed segment with forged rows.
    tampered = original_body.replace(b'"row_hash": "', b'"row_hash": "00', 1)
    client.put_object(Bucket=bucket, Key="segment-0001.jsonl", Body=tampered)

    # verify reads the latest version → Merkle root mismatch fires.
    rep = audit_archive.verify_archive()
    assert rep["ok"] is False
    types = {a["type"] for a in rep["anomalies"]}
    assert "merkle_root_mismatch" in types, rep["anomalies"]

    # ...and the SEALED version is still intact (versioning is the evidence trail).
    versions = client.list_object_versions(Bucket=bucket, Prefix="segment-0001.jsonl")
    assert len(versions.get("Versions", [])) == 2
    sealed = client.get_object(
        Bucket=bucket, Key="segment-0001.jsonl", VersionId=original_version
    )
    assert sealed["Body"].read() == original_body


# ---------------------------------------------------------------------------
# 6. Live-DB tamper after archival is still detected in s3 mode.
# ---------------------------------------------------------------------------
def test_live_tamper_detected_in_s3_mode(s3_archive):
    import sqlite3

    ids = _write_rows(s3_archive["writer"], 3)
    audit_archive.seal_next_segment()
    assert audit_archive.verify_archive()["ok"] is True

    conn = sqlite3.connect(config.AUDIT_DB_PATH)
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    conn.execute(
        "UPDATE audit SET row_hash = ? WHERE audit_id = ?",
        ("deadbeef" * 8, ids[1]),
    )
    conn.commit()
    conn.close()

    rep = audit_archive.verify_archive()
    assert rep["ok"] is False
    tampered = [a for a in rep["anomalies"] if a["type"] == "live_row_tampered"]
    assert any(a["audit_id"] == ids[1] for a in tampered)


# ---------------------------------------------------------------------------
# 7. COMPLIANCE mode — the production posture for the Q13 retention. Objects
#    written here can NEVER be removed before expiry, so this only runs where
#    the store is thrown away afterwards: the CI services job sets
#    ARCHIVE_S3_COMPLIANCE_TEST=1. The tests above use GOVERNANCE so a dev
#    store stays cleanable; RustFS has had COMPLIANCE-specific bugs, e.g.
#    https://github.com/rustfs/rustfs/issues/3174 and discussion #1459.
#    This exercises the STORE's COMPLIANCE semantics with raw S3 calls, not
#    the archiver's own ARCHIVE_S3_RETENTION_MODE=COMPLIANCE path.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    os.getenv("ARCHIVE_S3_COMPLIANCE_TEST") != "1",
    reason="writes undeletable objects; CI's throwaway store only",
)
def test_compliance_retention_cannot_be_bypassed_or_shortened():
    client = _store_or_skip()
    bucket = f"pm-compliance-{uuid.uuid4().hex[:12]}"
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    until = datetime.now(UTC) + timedelta(days=1)
    put = client.put_object(
        Bucket=bucket,
        Key="segment-0001.jsonl",
        Body=b'{"row_hash": "x"}',
        ObjectLockMode="COMPLIANCE",
        ObjectLockRetainUntilDate=until,
    )
    version_id = put["VersionId"]

    def refused(call):
        # A refusal, not a missing feature or a server fault: those would
        # pass a bare pytest.raises(ClientError) without proving anything.
        with pytest.raises(ClientError) as exc:
            call()
        code = exc.value.response["Error"]["Code"]
        assert code not in ("NotImplemented", "MethodNotAllowed", "ServiceUnavailable"), code
        assert not code.startswith("Internal"), code

    def retained_until():
        return client.get_object_retention(
            Bucket=bucket, Key="segment-0001.jsonl", VersionId=version_id
        )["Retention"]["RetainUntilDate"]

    # Controls — so the refusals below cannot be vacuous: a GOVERNANCE
    # version IS removable with the bypass, and a COMPLIANCE retention CAN be
    # extended (the retention API works on this store).
    gov = client.put_object(
        Bucket=bucket,
        Key="governance-control",
        Body=b"x",
        ObjectLockMode="GOVERNANCE",
        ObjectLockRetainUntilDate=until,
    )
    client.delete_object(
        Bucket=bucket,
        Key="governance-control",
        VersionId=gov["VersionId"],
        BypassGovernanceRetention=True,
    )
    until = until + timedelta(hours=1)
    client.put_object_retention(
        Bucket=bucket,
        Key="segment-0001.jsonl",
        VersionId=version_id,
        Retention={"Mode": "COMPLIANCE", "RetainUntilDate": until},
    )
    assert abs((retained_until() - until).total_seconds()) < 2  # really extended

    # Not even the governance bypass removes a COMPLIANCE version...
    refused(
        lambda: client.delete_object(
            Bucket=bucket,
            Key="segment-0001.jsonl",
            VersionId=version_id,
            BypassGovernanceRetention=True,
        )
    )
    # ...nor can its retention be shortened, or switched to GOVERNANCE.
    refused(
        lambda: client.put_object_retention(
            Bucket=bucket,
            Key="segment-0001.jsonl",
            VersionId=version_id,
            Retention={"Mode": "COMPLIANCE", "RetainUntilDate": until - timedelta(hours=12)},
        )
    )
    refused(
        lambda: client.put_object_retention(
            Bucket=bucket,
            Key="segment-0001.jsonl",
            VersionId=version_id,
            Retention={"Mode": "GOVERNANCE", "RetainUntilDate": until},
            BypassGovernanceRetention=True,
        )
    )

    # The refused changes left the retention exactly as extended.
    assert abs((retained_until() - until).total_seconds()) < 2
    head = client.head_object(Bucket=bucket, Key="segment-0001.jsonl", VersionId=version_id)
    assert head["ObjectLockMode"] == "COMPLIANCE"
    obj = client.get_object(Bucket=bucket, Key="segment-0001.jsonl", VersionId=version_id)
    assert obj["Body"].read() == b'{"row_hash": "x"}'
