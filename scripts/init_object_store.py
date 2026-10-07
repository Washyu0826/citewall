#!/usr/bin/env python
"""One-shot bootstrap of the Q13 WORM archive bucket (ARCHIVE_BACKEND=s3).

Works against any S3 store with Object Lock: RustFS in docker-compose.yml
(MinIO, the original target, left Docker Hub in 2026-09 — FAILURE_LOG E-4),
or AWS S3 / another provider by pointing ARCHIVE_S3_ENDPOINT at it.

Creates the audit-archive bucket WITH Object Lock enabled (which implies —
and auto-enables — versioning). Object Lock can ONLY be enabled at bucket
creation time, which is why this script exists instead of letting the
archiver lazily create the bucket: a lazily-created, lock-less bucket would
silently lose the WORM property.

Idempotent: re-running against an existing bucket verifies its Object Lock
configuration and exits 0; a pre-existing bucket WITHOUT Object Lock is a
hard error (delete it and re-run — Object Lock cannot be retrofitted).

Usage (after `docker compose up -d rustfs`):

    python scripts/init_object_store.py

Connection settings come from backend/shared/config.py (env-overridable):
ARCHIVE_S3_ENDPOINT / ARCHIVE_S3_ACCESS_KEY / ARCHIVE_S3_SECRET_KEY /
ARCHIVE_S3_BUCKET / ARCHIVE_S3_REGION. RustFS console: http://localhost:19001
(credentials = RUSTFS_ACCESS_KEY / RUSTFS_SECRET_KEY in .env).

No vendor CLI required — pure boto3, same dependency the archiver itself uses.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

# Make `import backend...` work when run as `python scripts/init_object_store.py`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main() -> int:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError, EndpointConnectionError

    # Importing the backend config runs the SERVICES' boot guards, one of
    # which refuses the published placeholder JWT_SECRET. This one-shot tool
    # only reads ARCHIVE_S3_* and never issues or checks a token, so it must
    # not need the service secrets: without this it crashed for anyone who
    # had not exported .env (and in CI, FAILURE_LOG B-49). A throwaway value,
    # for this process only; an exported JWT_SECRET is left untouched.
    os.environ.setdefault("JWT_SECRET", secrets.token_hex(32))
    from backend.shared.config import settings

    endpoint = settings.ARCHIVE_S3_ENDPOINT
    bucket = settings.ARCHIVE_S3_BUCKET

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.ARCHIVE_S3_ACCESS_KEY,
        aws_secret_access_key=settings.ARCHIVE_S3_SECRET_KEY,
        region_name=settings.ARCHIVE_S3_REGION,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
    )

    print(f">> S3 endpoint    : {endpoint}")
    print(f">> Target bucket  : {bucket}")

    # --- reachability ------------------------------------------------------
    try:
        client.list_buckets()
    except EndpointConnectionError:
        print(
            f"ERR the object store is not reachable at {endpoint}. "
            "Start it first: docker compose up -d rustfs",
            file=sys.stderr,
        )
        return 1
    except ClientError as exc:
        print(f"ERR the object store refused the credentials: {exc}", file=sys.stderr)
        return 1

    # --- create-or-verify ---------------------------------------------------
    try:
        client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
        print(f"OK  created bucket {bucket!r} with Object Lock ENABLED (versioning implied)")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f">> bucket {bucket!r} already exists — verifying Object Lock...")
        else:
            print(f"ERR create_bucket failed: {exc}", file=sys.stderr)
            return 1

    # --- verify Object Lock is actually on ----------------------------------
    try:
        conf = client.get_object_lock_configuration(Bucket=bucket)
        enabled = conf.get("ObjectLockConfiguration", {}).get("ObjectLockEnabled")
        if enabled != "Enabled":
            raise ClientError(
                {"Error": {"Code": "ObjectLockConfigurationNotFoundError", "Message": ""}},
                "GetObjectLockConfiguration",
            )
    except ClientError:
        print(
            f"ERR bucket {bucket!r} exists but Object Lock is NOT enabled. "
            "Object Lock cannot be retrofitted — delete the bucket and re-run "
            "this script (or point ARCHIVE_S3_BUCKET at a fresh name).",
            file=sys.stderr,
        )
        return 1
    print(f"OK  Object Lock verified on {bucket!r}")

    # NOTE: deliberately NO bucket-level default retention rule — the archiver
    # applies per-object retention (ARCHIVE_S3_RETENTION_MODE/_DAYS) on each
    # sealed segment, and the rewritable _state.json cursor must stay unlocked.
    print(
        f"OK  ready. Sealed segments will carry "
        f"{settings.ARCHIVE_S3_RETENTION_MODE} retention for "
        f"{settings.ARCHIVE_S3_RETENTION_DAYS} days. "
        f"Enable with ARCHIVE_BACKEND=s3."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
