"""Audit log (Q13).

POC implements append-only locally; the trigger blocks UPDATE / DELETE so
the DBA can't tamper inadvertently.  Production must additionally:
    - Write to S3 Object Lock / Azure Immutable Blob hourly.
    - Sign each row chain with HMAC of previous row hash (tamper evidence).
    - Replicate to a 2nd tenant for compliance independence.

Every gateway-handled request produces exactly one audit row.

Backends (``AUDIT_BACKEND`` in backend/shared/config.py):

  * ``sqlite``   (default) — :class:`AuditWriter`. Append-only local file,
    UPDATE/DELETE blocked by SQLite triggers. Zero infra; what the demo and
    the entire test suite run on.
  * ``postgres`` — :class:`PostgresAuditWriter`. Same schema, same hash-chain
    format, same append-only semantics enforced by a plpgsql trigger that
    RAISEs on UPDATE/DELETE. Point ``POSTGRES_URL`` at the compose container
    (host port **15432** on the delivery box — 5432 is taken).

The hash-chain *format* is identical across backends (the chain payload and
``_hash_payload`` live on the shared base class), and ALL verification logic
(``verify_chain`` / ``verify_global_chain`` / ``verify_cross_tenant``) is
implemented ONCE on :class:`_BaseAuditWriter` against an abstract ordered-row
fetch — so a chain written by one backend and migrated row-for-row to the
other still verifies.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.shared.config import AUDIT_DB_PATH
from backend.shared.models import User

logger = logging.getLogger(__name__)

# Code-controlled SYSTEM SENTINEL tenants — legitimate tenant_id values written
# by the gateway itself for events that occur BEFORE a real tenant identity is
# known. ``_preauth_`` labels pre-auth audit rows (magic-link request/consume,
# Q12 — see backend/gateway/main.py). verify_global_chain's tenant-whitelist
# pass treats these as known so they are never mistaken for a smuggled ghost
# tenant. Keep in sync with the sentinels main.py actually writes.
_SYSTEM_SENTINEL_TENANTS: frozenset[str] = frozenset({"_preauth_"})


_DDL = """
CREATE TABLE IF NOT EXISTS audit (
    audit_id           TEXT PRIMARY KEY,
    timestamp_utc      TEXT NOT NULL,
    timestamp_local    TEXT NOT NULL,
    user_id            TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    case_id            TEXT,
    endpoint           TEXT NOT NULL,
    request_hash       TEXT NOT NULL,
    response_hash      TEXT,
    masked_field_rules TEXT NOT NULL,
    model_used         TEXT,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    latency_ms         INTEGER,
    policy_decisions   TEXT NOT NULL,
    prev_row_hash      TEXT,
    row_hash           TEXT NOT NULL,
    hash_version       INTEGER,
    hash_key_id        TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit(user_id, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit(tenant_id, timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit(case_id, timestamp_utc DESC);

-- Hard block on tampering.  Trigger errors out.
CREATE TRIGGER IF NOT EXISTS audit_no_update
    BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit table is append-only'); END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete
    BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit table is append-only'); END;
"""

# Postgres twin of _DDL. Differences are mechanical, not semantic:
#   * an explicit BIGSERIAL ``row_seq`` stands in for SQLite's implicit rowid
#     as the strictly-monotonic insertion-order column (the chain walks it);
#   * the append-only guard is a plpgsql trigger function that RAISEs — the
#     exact Postgres equivalent of SQLite's RAISE(ABORT, ...) triggers.
# Everything the hash chain commits to (column set, value shapes) is identical.
# Kept as discrete statements: psycopg3's extended query protocol executes one
# statement per ``execute()`` (unlike sqlite3's executescript).
_PG_DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS audit (
        row_seq            BIGSERIAL PRIMARY KEY,
        audit_id           TEXT UNIQUE NOT NULL,
        timestamp_utc      TEXT NOT NULL,
        timestamp_local    TEXT NOT NULL,
        user_id            TEXT NOT NULL,
        tenant_id          TEXT NOT NULL,
        case_id            TEXT,
        endpoint           TEXT NOT NULL,
        request_hash       TEXT NOT NULL,
        response_hash      TEXT,
        masked_field_rules TEXT NOT NULL,
        model_used         TEXT,
        prompt_tokens      INTEGER,
        completion_tokens  INTEGER,
        latency_ms         INTEGER,
        policy_decisions   TEXT NOT NULL,
        prev_row_hash      TEXT,
        row_hash           TEXT NOT NULL,
        hash_version       INTEGER,
        hash_key_id        TEXT
    )
    """,
    # Q26 idempotent migration for tables created before hash_version existed
    # (NULL = legacy v1 row). ALTER is not an UPDATE/DELETE, so the append-only
    # triggers do not fire.
    "ALTER TABLE audit ADD COLUMN IF NOT EXISTS hash_version INTEGER",
    # Q21 key rotation: which HMAC key signed the row (NULL = pre-rotation
    # row, signed with the legacy single key).
    "ALTER TABLE audit ADD COLUMN IF NOT EXISTS hash_key_id TEXT",
    "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit(user_id, timestamp_utc DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit(tenant_id, timestamp_utc DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_case ON audit(case_id, timestamp_utc DESC)",
    """
    CREATE OR REPLACE FUNCTION audit_no_tamper() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'audit table is append-only';
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE OR REPLACE TRIGGER audit_no_update
        BEFORE UPDATE ON audit
        FOR EACH ROW EXECUTE FUNCTION audit_no_tamper()
    """,
    """
    CREATE OR REPLACE TRIGGER audit_no_delete
        BEFORE DELETE ON audit
        FOR EACH ROW EXECUTE FUNCTION audit_no_tamper()
    """,
)

# The 10 chain-relevant columns, in the canonical order every fetch uses.
_CHAIN_COLS = (
    "audit_id, timestamp_utc, user_id, tenant_id, case_id, "
    "endpoint, request_hash, response_hash, prev_row_hash, row_hash"
)

# Chain columns + every other persisted field: what a v2 (HMAC, Q26) row_hash
# commits to. Verification and archival read this wider set; _CHAIN_COLS stays
# the stable 10-tuple for existing callers.
_VERIFY_COLS = (
    _CHAIN_COLS + ", timestamp_local, masked_field_rules, model_used, prompt_tokens, "
    "completion_tokens, latency_ms, policy_decisions, hash_version, hash_key_id"
)

# Hash-chain versions. v1: unkeyed sha256 over the chain columns (legacy rows).
# v2: HMAC-SHA256 (AUDIT_HMAC_KEY) over ALL persisted fields — a DB-write
# attacker can neither edit policy_decisions / model / tokens undetected nor
# recompute the chain tail without the key.
HASH_V1 = 1
HASH_V2 = 2

_dev_hmac_key_warned = False

# kid recorded for rows signed with the derived mock/test dev key.
DEV_KID = "dev"
# kid of the legacy single AUDIT_HMAC_KEY; also used for v2 rows written before
# rotation support existed (hash_key_id NULL).
LEGACY_KID = "k1"


def _dev_key() -> bytes:
    global _dev_hmac_key_warned
    from backend.shared.config import settings

    if not _dev_hmac_key_warned:
        logger.warning(
            "No audit HMAC key configured — deriving a DEV key for the audit HMAC "
            "chain from JWT_SECRET. Set AUDIT_HMAC_KEY(S) for any real deployment."
        )
        _dev_hmac_key_warned = True
    return hashlib.sha256(
        b"patentmind-dev-audit-hmac::" + settings.JWT_SECRET.encode("utf-8")
    ).digest()


def _keyring() -> tuple[dict[str, bytes], str]:
    """(kid -> key, active kid). Q21 rotation.

    ``AUDIT_HMAC_KEYS="k1:...,k2:..."`` + ``AUDIT_HMAC_ACTIVE_KID`` is the
    rotation form; a lone ``AUDIT_HMAC_KEY`` is kid ``k1``; with neither
    (mock/test only — config refuses to boot otherwise) the derived dev key is
    kid ``dev``. Read on every call so tests / hot config changes apply.
    """
    from backend.shared.config import settings

    ring: dict[str, bytes] = {}
    for part in (settings.AUDIT_HMAC_KEYS or "").split(","):
        kid, sep, secret = part.strip().partition(":")
        if sep and kid.strip() and secret.strip():
            ring[kid.strip()] = secret.strip().encode("utf-8")
    if settings.AUDIT_HMAC_KEY and LEGACY_KID not in ring:
        ring[LEGACY_KID] = settings.AUDIT_HMAC_KEY.encode("utf-8")
    if ring:
        active = settings.AUDIT_HMAC_ACTIVE_KID or (
            LEGACY_KID if LEGACY_KID in ring else next(iter(ring))
        )
        return ring, active
    return {DEV_KID: _dev_key()}, DEV_KID


def _key_for(kid: str | None) -> bytes | None:
    """Key for a stored row's kid; ``None`` when the ring no longer holds it
    (the row is then UNVERIFIABLE — never silently accepted). A NULL kid is a
    pre-rotation v2 row, signed with the legacy single key (or the dev key)."""
    ring, _active = _keyring()
    if kid is None:
        return ring.get(LEGACY_KID) or ring.get(DEV_KID)
    return ring.get(kid)


def _audit_hmac_key() -> bytes:
    """Active signing key (back-compat helper)."""
    ring, active = _keyring()
    return ring[active]


def _v2_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Canonical v2 payload from a row dict (DB column names). JSON columns are
    committed as their STORED text so verification never depends on
    re-serialisation details."""
    return {
        "v": HASH_V2,
        "audit_id": row["audit_id"],
        "ts": row["timestamp_utc"],
        "ts_local": row["timestamp_local"],
        "user": row["user_id"],
        "tenant": row["tenant_id"],
        "case": row["case_id"],
        "endpoint": row["endpoint"],
        "req": row["request_hash"],
        "resp": row["response_hash"],
        "masked": row["masked_field_rules"],
        "model": row["model_used"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "latency_ms": row["latency_ms"],
        "policy": row["policy_decisions"],
        "prev": row["prev_row_hash"],
    }


def _hmac_hex(payload: dict[str, Any], key: bytes | None = None) -> str:
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    k = key if key is not None else _audit_hmac_key()
    return hmac.new(k, s.encode("utf-8"), hashlib.sha256).hexdigest()


UNVERIFIABLE_PREFIX = "<unverifiable: unknown hash_key_id "


_LIST_COLS = (
    "audit_id, timestamp_utc, user_id, case_id, endpoint, "
    "model_used, prompt_tokens, completion_tokens, latency_ms, "
    "masked_field_rules, policy_decisions"
)


_INSERT_SQL = """
    INSERT INTO audit (
        audit_id, timestamp_utc, timestamp_local, user_id, tenant_id, case_id,
        endpoint, request_hash, response_hash, masked_field_rules,
        model_used, prompt_tokens, completion_tokens, latency_ms,
        policy_decisions, prev_row_hash, row_hash, hash_version, hash_key_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# Marker for a payload that is already reduced to its sha256 digest (outbox).
PREHASHED_KEY = "__sha256__"


class _BaseAuditWriter:
    """Backend-agnostic audit writer / verifier.

    Subclasses provide:
      * ``_ORDER_COL``       — the strictly-monotonic insertion-order column
                               (SQLite: implicit ``rowid``; Postgres: ``row_seq``).
      * ``_fetchall(sql, params)`` — run a read query (``?`` placeholders,
                               translated by the subclass) and return tuples.
      * ``_append_chained(build)`` — in ONE transaction holding a lock that
                               excludes other processes: read the chain tail's
                               ``row_hash``, call ``build(prev_hash)`` for the
                               row values, insert them, commit.

    Everything else — the write flow, the hash-chain format, and ALL THREE
    verify functions — lives here, shared verbatim by both backends.
    """

    _ORDER_COL: str = "rowid"

    # -- abstract storage hooks -------------------------------------------
    def _fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        raise NotImplementedError

    def _append_chained(self, build: Callable[[str], tuple]) -> None:
        raise NotImplementedError

    # -- shared hash / chain primitives -----------------------------------
    @staticmethod
    def _hash_payload(obj: Any) -> str:
        if obj is None:
            return ""
        # The outbox stores only the digest of a payload (never the raw OA
        # text) — replay hands it back pre-hashed so the chained hash is the
        # one the original write would have produced.
        if isinstance(obj, dict) and set(obj) == {PREHASHED_KEY}:
            return str(obj[PREHASHED_KEY])
        s = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(s.encode()).hexdigest()

    def _tail_sql(self) -> str:
        return f"SELECT row_hash FROM audit ORDER BY {self._ORDER_COL} DESC LIMIT 1"  # noqa: S608

    def _fetch_chain_rows(self, tenant_id: str | None = None) -> list[tuple]:
        """All chain-relevant rows in insertion order (optionally one tenant)."""
        if tenant_id is None:
            return self._fetchall(
                f"SELECT {_CHAIN_COLS} FROM audit ORDER BY {self._ORDER_COL} ASC"  # noqa: S608
            )
        return self._fetchall(
            f"SELECT {_CHAIN_COLS} FROM audit "  # noqa: S608
            f"WHERE tenant_id = ? ORDER BY {self._ORDER_COL} ASC",
            (tenant_id,),
        )

    def _fetch_verify_rows(self) -> list[dict[str, Any]]:
        """Every row with ALL persisted fields (``_VERIFY_COLS``) as dicts, in
        global insertion order — what v2 verification recomputes over."""
        cols = [c.strip() for c in _VERIFY_COLS.split(",")]
        raw = self._fetchall(
            f"SELECT {_VERIFY_COLS} FROM audit ORDER BY {self._ORDER_COL} ASC"  # noqa: S608
        )
        return [dict(zip(cols, r, strict=True)) for r in raw]

    @classmethod
    def expected_row_hash(cls, row: dict[str, Any]) -> str:
        """Recompute a row's hash per its recorded ``hash_version``.

        NULL/1 = legacy v1 (unkeyed sha256 over the chain columns); 2 = v2
        HMAC over every persisted field. Unknown versions never verify.
        """
        version = row.get("hash_version") or HASH_V1
        if version == HASH_V2:
            key = _key_for(row.get("hash_key_id"))
            if key is None:
                # The signing key left the ring: we cannot tell an intact row
                # from a forged one, so it must never count as verified.
                return f"{UNVERIFIABLE_PREFIX}{row.get('hash_key_id')!r}>"
            return _hmac_hex(_v2_payload(row), key)
        if version == HASH_V1:
            return cls._hash_payload(
                {
                    "audit_id": row["audit_id"],
                    "ts": row["timestamp_utc"],
                    "user": row["user_id"],
                    "tenant": row["tenant_id"],
                    "case": row["case_id"],
                    "endpoint": row["endpoint"],
                    "req": row["request_hash"],
                    "resp": row["response_hash"],
                    "prev": row["prev_row_hash"],
                }
            )
        return f"<unsupported hash_version {version!r}>"

    @classmethod
    def _row_is_valid(cls, row: dict[str, Any], seen_v2: bool) -> bool:
        """Hash matches AND no v1 row appears after the chain went v2 — a raw
        insert labelled v1 would otherwise dodge the HMAC (downgrade attack)."""
        version = row.get("hash_version") or HASH_V1
        if seen_v2 and version != HASH_V2:
            return False
        return cls.expected_row_hash(row) == row["row_hash"]

    @staticmethod
    def _is_unverifiable(row: dict[str, Any]) -> bool:
        """v2 row whose recorded signing key is not in the current ring."""
        version = row.get("hash_version") or HASH_V1
        return version == HASH_V2 and _key_for(row.get("hash_key_id")) is None

    def read_all_rows(self) -> list[dict[str, Any]]:
        """Every audit row as dicts, in insertion order.

        This is the read surface the WORM archiver (audit_archive.py) seals
        from, so it MUST be insertion-ordered and backend-agnostic. It returns
        the chain columns plus every v2-hashed field (``_VERIFY_COLS``).
        """
        return self._fetch_verify_rows()

    # -- write -------------------------------------------------------------
    def write(
        self,
        *,
        user: User,
        case_id: str | None,
        endpoint: str,
        request_payload: Any,
        response_payload: Any,
        masked_rules: list[str],
        model_used: str | None,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        latency_ms: int,
        policy_decisions: dict[str, bool],
    ) -> str:
        now_utc = datetime.now(UTC)
        # POC: local timezone shown as UTC+8 for Taiwan demo
        now_local = now_utc.astimezone(tz=None).isoformat()

        audit_id = str(uuid.uuid4())
        request_hash = self._hash_payload(request_payload)
        response_hash = self._hash_payload(response_payload)

        # The read-tail → compute → insert sequence must be atomic ACROSS
        # PROCESSES, not just threads: two gateway replicas that both chain
        # off the same tail fork the chain, and verify then reports it as
        # tampering (H-10). _append_chained runs `build` inside one database
        # transaction that holds a cross-process write lock.
        def build(prev_hash: str) -> tuple:
            # Tamper-evident chain (v2, Q26): HMAC over EVERY persisted field
            # plus prev_row_hash, so policy_decisions / model / tokens are
            # covered and the tail cannot be recomputed without the key.
            row = {
                "audit_id": audit_id,
                "timestamp_utc": now_utc.isoformat(),
                "timestamp_local": now_local,
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
                "case_id": case_id,
                "endpoint": endpoint,
                "request_hash": request_hash,
                "response_hash": response_hash,
                "masked_field_rules": json.dumps(masked_rules),
                "model_used": model_used,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
                "policy_decisions": json.dumps(policy_decisions),
                "prev_row_hash": prev_hash,
            }
            ring, active_kid = _keyring()
            row_hash = _hmac_hex(_v2_payload(row), ring[active_kid])
            return (
                row["audit_id"],
                row["timestamp_utc"],
                row["timestamp_local"],
                row["user_id"],
                row["tenant_id"],
                row["case_id"],
                row["endpoint"],
                row["request_hash"],
                row["response_hash"],
                row["masked_field_rules"],
                row["model_used"],
                row["prompt_tokens"],
                row["completion_tokens"],
                row["latency_ms"],
                row["policy_decisions"],
                row["prev_row_hash"],
                row_hash,
                HASH_V2,
                active_kid,
            )

        self._append_chained(build)
        return audit_id

    # -- reads -------------------------------------------------------------
    def list_for_tenant(self, tenant_id: str, limit: int = 100) -> list[dict]:
        raw = self._fetchall(
            f"SELECT {_LIST_COLS} FROM audit "  # noqa: S608
            f"WHERE tenant_id = ? ORDER BY {self._ORDER_COL} DESC LIMIT ?",
            (tenant_id, limit),
        )
        cols = [c.strip() for c in _LIST_COLS.split(",")]
        rows = []
        for r in raw:
            d = dict(zip(cols, r, strict=True))
            d["masked_field_rules"] = json.loads(d["masked_field_rules"])
            d["policy_decisions"] = json.loads(d["policy_decisions"])
            rows.append(d)
        return rows

    # -- verification (SHARED across backends — Q13) ------------------------
    def verify_chain(self, tenant_id: str) -> dict:
        """Walk the chain, recompute hashes, report any tamper detected.

        For production: run nightly + alert on mismatch.
        """
        ok = 0
        broken: list[str] = []
        unverifiable: list[str] = []
        prev = ""
        # The chain is GLOBAL (the writer links each row to the previous row of
        # ANY tenant), so walking only this tenant's rows would expect the
        # wrong predecessor and flag an intact chain as broken whenever another
        # tenant's (or _preauth_) row sits in between. Walk every row to track
        # the true predecessor, but check + report only this tenant's rows.
        seen_v2 = False
        for row in self._fetch_verify_rows():
            audit_id, recorded_row = row["audit_id"], row["row_hash"]
            row_valid = self._row_is_valid(row, seen_v2)
            seen_v2 = seen_v2 or row.get("hash_version") == HASH_V2
            if row["tenant_id"] != tenant_id:
                prev = recorded_row
                continue
            if row["prev_row_hash"] != prev:
                broken.append(audit_id)
            if not row_valid:
                broken.append(audit_id)
                if self._is_unverifiable(row):
                    unverifiable.append(audit_id)
            else:
                ok += 1
            prev = recorded_row
        # Unverifiable rows (signing key missing from the ring, Q21) are ALSO
        # in `broken` (fail-closed for existing alarms); `unverifiable` says why.
        return {
            "verified": ok,
            "broken": broken,
            "unverifiable": unverifiable,
            "tenant": tenant_id,
        }

    def verify_global_chain(self) -> dict:
        """Walk every audit row in global insertion order + run cross-cutting
        checks no per-tenant walk can perform (H-4 fix — CLAUDE.md §7
        pitfall #4).

        Important wrinkle the per-tenant ``verify_chain`` does NOT handle:
        the hash chain is GLOBAL (the writer's tail lookup in
        ``_append_chained`` is not tenant-scoped), so ``prev_row_hash`` on a tenant_b row may
        legitimately point to a tenant_a row_hash. Walking only
        ``WHERE tenant_id = 'tenant_b'`` and expecting tenant_b's first
        row to have ``prev=''`` is therefore wrong in the multi-tenant
        case — it flags an intact chain as broken. Global verify walks
        every row in insertion order so the chain is reconstructed faithfully.

        This verifier surfaces THREE classes of anomaly:

        1. **Hash chain integrity (global)** — every row's
           ``row_hash`` is recomputed from its payload + recorded
           ``prev_row_hash``; mismatch flags the row as broken. Adjacent
           rows must form a chain (each row's ``prev_row_hash`` == the
           previous row's ``row_hash``).

        2. **Tenant whitelist** — any row whose ``tenant_id`` is NOT in
           ``settings.DEMO_TENANTS`` is flagged as ``unknown_tenant``.
           Catches typos (``tenat_a``), probes (``tenant_zzz``), and any
           future ghost tenant smuggled in by a compromised DBA.

        3. **prev_row_hash referential integrity** — every non-empty
           ``prev_row_hash`` must reference a ``row_hash`` that exists
           somewhere in the table. Dangling prev = row was tampered with
           after insert OR written by a process bypassing the audit writer.

        Returns:

            {
              "verified": int,                          # rows that passed
              "broken": list[tuple[tenant_id, audit_id]],
              "by_tenant": {
                  tenant_id: {
                      "verified": int,
                      "broken": list[audit_id],         # audit_ids only,
                                                        # for backward-compat
                                                        # shape with existing
                                                        # per-tenant verify
                      "tenant": tenant_id,
                      "unknown_tenant": bool,           # only when true
                  },
                  ...
              }
            }
        """
        # Load every row in insertion order so we reconstruct the GLOBAL
        # chain rather than a per-tenant view. The same fetch serves the
        # referential-integrity pass (full set of row_hashes) so the whole
        # verify is one storage round-trip on either backend.
        all_rows = self._fetch_verify_rows()
        all_row_hashes: set[str] = {r["row_hash"] for r in all_rows}

        # Cross-import settings here (not at module top) so a test that
        # monkeypatches DEMO_TENANTS via settings sees the override.
        from backend.shared.config import settings as _settings

        # Known tenants = real demo tenants PLUS code-controlled SYSTEM SENTINEL
        # tenants. Pre-auth audit rows (magic-link request/consume — Q12) are
        # written before any tenant identity exists, under the documented
        # ``_preauth_`` sentinel (see backend/gateway/main.py). Those rows are
        # legitimate and MUST NOT be flagged ``unknown_tenant`` — that check
        # exists to catch a DBA-smuggled ghost/typo tenant, not our own
        # sentinel. Without this, any global chain verify after someone uses
        # magic-link would show false ``broken`` rows forever.
        known_tenants: set[str] = set(_settings.DEMO_TENANTS.keys()) | _SYSTEM_SENTINEL_TENANTS

        by_tenant: dict[str, dict] = {}
        broken: list[tuple[str, str]] = []
        unverifiable: list[tuple[str, str]] = []
        verified_total = 0

        # Pass 1 — walk the global chain, recompute hashes, partition
        # per-tenant. ``prev`` tracks the expected prev_row_hash for the
        # NEXT row (starts empty for the first global row).
        prev = ""
        seen_v2 = False
        for row in all_rows:
            audit_id, tid, recorded_row = row["audit_id"], row["tenant_id"], row["row_hash"]
            per = by_tenant.setdefault(tid, {"verified": 0, "broken": [], "tenant": tid})

            row_broken = False
            if row["prev_row_hash"] != prev:
                row_broken = True
            if not self._row_is_valid(row, seen_v2):
                row_broken = True
                if self._is_unverifiable(row):
                    unverifiable.append((tid, audit_id))
            seen_v2 = seen_v2 or row.get("hash_version") == HASH_V2

            if row_broken:
                per["broken"].append(audit_id)
                broken.append((tid, audit_id))
            else:
                per["verified"] += 1
                verified_total += 1

            prev = recorded_row

        # Pass 2 — tenant whitelist. Any tenant_id not in DEMO_TENANTS is
        # flagged; every row from that tenant is added to broken even if
        # its hash chain happens to be internally consistent (we have no
        # policy basis for accepting rows from an unknown tenant).
        for tid, per in by_tenant.items():
            if tid not in known_tenants:
                per["unknown_tenant"] = True
                for row in all_rows:
                    if row["tenant_id"] != tid:
                        continue
                    pair = (tid, row["audit_id"])
                    if pair not in broken:
                        broken.append(pair)

        # Pass 3 — prev_row_hash referential integrity. Every non-empty
        # prev_row_hash MUST point to some row's row_hash. Catches the
        # case where a row was written outside the audit writer (which is
        # the only thing that calls ``_last_row_hash`` to set prev).
        for row in all_rows:
            audit_id, tenant_id, prev_hash = row["audit_id"], row["tenant_id"], row["prev_row_hash"]
            if prev_hash and prev_hash not in all_row_hashes:
                pair = (tenant_id, audit_id)
                if pair not in broken:
                    broken.append(pair)

        return {
            "verified": verified_total,
            "broken": broken,
            "unverifiable": unverifiable,
            "by_tenant": by_tenant,
        }

    # ------------------------------------------------------------------
    # Cross-tenant verification helper (CLAUDE.md §7 pitfall #4).
    #
    # ``verify_chain`` walks ONE tenant. ``verify_global_chain`` walks the
    # whole table in insertion order. Neither answers the specific auditor
    # question "are tenant A and tenant B each internally well-formed, and
    # is there any structural anomaly that ONLY shows up when you compare
    # two tenants side by side?" — e.g. a row of tenant B whose row_hash
    # collides with a tenant A row (a sign of a copy-paste injection), or a
    # tenant present in the data that the caller did not expect.
    #
    # ``verify_cross_tenant`` is that purpose-built helper. It is additive:
    # it does NOT replace the other two. It runs the authoritative global
    # walk once (so the hash chain is reconstructed faithfully — the global
    # chain spans tenants), then layers cross-tenant–only assertions on top.
    # ------------------------------------------------------------------
    def verify_cross_tenant(self, tenant_ids: list[str] | None = None) -> dict:
        """Verify two-or-more tenants' chains side by side.

        Runs the global walk (authoritative for the spanning hash chain),
        then surfaces anomalies that are only visible when comparing tenants:

        1. **Per-tenant integrity** — each requested tenant's rows must all
           verify under the global walk (no broken rows attributed to it).
        2. **row_hash uniqueness across tenants** — a ``row_hash`` value that
           appears under two *different* tenant_ids is flagged
           ``cross_tenant_hash_collision``. Because the chain hash commits to
           ``tenant``, an honest writer can never mint the same ``row_hash``
           for two tenants; a collision means a row was copied across tenant
           boundaries (injection) or the chain was forged.
        3. **Expected-tenant set** — when ``tenant_ids`` is given, any tenant
           found in the data but NOT requested is reported under
           ``unexpected_tenants`` (the auditor asked about A and B but the
           table also holds C — worth knowing). Conversely a requested tenant
           with zero rows is reported under ``missing_tenants``.

        Args:
            tenant_ids: the tenants the auditor expects/cares about. When
                ``None``, every tenant present is verified and the
                expected-set checks are skipped.

        Returns::

            {
              "ok": bool,                       # no anomalies at all
              "tenants_verified": [tenant_id, ...],
              "per_tenant": {tid: {"verified": int, "broken": [audit_id,...]}},
              "anomalies": [ {type, ...}, ... ],
              "global_verified": int,           # passthrough from global walk
              "global_broken": [(tid, audit_id), ...],
            }
        """
        global_result = self.verify_global_chain()
        by_tenant = global_result["by_tenant"]
        global_broken = global_result["broken"]

        anomalies: list[dict] = []

        # Determine the tenant universe we report on.
        present_tenants = set(by_tenant.keys())
        if tenant_ids is None:
            target = sorted(present_tenants)
        else:
            target = list(tenant_ids)
            requested = set(tenant_ids)
            # Tenants present in the data but the auditor didn't ask about.
            for tid in sorted(present_tenants - requested):
                anomalies.append({"type": "unexpected_tenant", "tenant_id": tid})
            # Tenants asked about but with no rows at all.
            for tid in sorted(requested - present_tenants):
                anomalies.append({"type": "missing_tenant", "tenant_id": tid})

        # (1) Per-tenant integrity: any broken row in a target tenant is an
        # anomaly attributed to that tenant.
        per_tenant: dict[str, dict] = {}
        for tid in target:
            rep = by_tenant.get(tid, {"verified": 0, "broken": []})
            per_tenant[tid] = {
                "verified": rep.get("verified", 0),
                "broken": list(rep.get("broken", [])),
            }
            for aid in rep.get("broken", []):
                anomalies.append({"type": "tenant_chain_break", "tenant_id": tid, "audit_id": aid})
            if rep.get("unknown_tenant"):
                anomalies.append({"type": "unknown_tenant", "tenant_id": tid})

        # (2) row_hash uniqueness across tenants. Build (row_hash ->
        # {tenant_id, ...}) over ALL rows and flag any hash seen under >1
        # tenant. One ordered scan keeps this O(rows) regardless of how many
        # tenants were requested.
        hash_owners: dict[str, set[str]] = {}
        hash_to_audit_ids: dict[str, list[tuple[str, str]]] = {}
        for row in self._fetch_chain_rows():
            audit_id, tid, row_hash = row[0], row[3], row[9]
            hash_owners.setdefault(row_hash, set()).add(tid)
            hash_to_audit_ids.setdefault(row_hash, []).append((tid, audit_id))
        for row_hash, owners in hash_owners.items():
            if len(owners) > 1:
                anomalies.append(
                    {
                        "type": "cross_tenant_hash_collision",
                        "row_hash": row_hash,
                        "tenants": sorted(owners),
                        "rows": hash_to_audit_ids[row_hash],
                    }
                )

        return {
            "ok": not anomalies and not global_broken,
            "tenants_verified": target,
            "per_tenant": per_tenant,
            "anomalies": anomalies,
            "global_verified": global_result["verified"],
            "global_broken": global_broken,
        }


class AuditWriter(_BaseAuditWriter):
    """SQLite audit backend (default — ``AUDIT_BACKEND=sqlite``)."""

    _ORDER_COL = "rowid"

    def __init__(self, path: Path = AUDIT_DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # timeout = how long a writer waits for another process's write lock
        # (BEGIN IMMEDIATE below) before raising "database is locked".
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
        self._conn.executescript(_DDL)
        _sqlite_migrate(self._conn)
        self._conn.commit()
        # Reads use their own READ-ONLY connection (M-13, parity with the
        # Postgres writer): they used to run on the writer's connection with
        # no lock, interleaving with an open BEGIN IMMEDIATE from another
        # thread. mode=ro also means the read path cannot mutate the table.
        self._read_lock = threading.Lock()
        self._read_conn = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False, timeout=30.0
        )

    def _fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._read_lock:
            return self._read_conn.execute(sql, params).fetchall()

    def _append_chained(self, build: Callable[[str], tuple]) -> None:
        # RLock serialises this process's threads (one shared connection);
        # BEGIN IMMEDIATE takes SQLite's RESERVED lock up front, so a writer
        # in ANOTHER process blocks until we commit and then reads our row
        # as its tail. A plain (deferred) transaction would let both read
        # the same tail before either writes.
        with self._lock:
            if self._conn.in_transaction:
                self._conn.commit()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._conn.execute(self._tail_sql()).fetchall()
                self._conn.execute(_INSERT_SQL, build(rows[0][0] if rows else ""))
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def ping(self) -> None:
        """Readiness (OBS-9): the WRITE connection answers. Not the read one —
        a long chain verify holds the read lock, and what readiness cares
        about is that this request's audit row can be written."""
        with self._lock:
            self._conn.execute("SELECT 1 FROM audit LIMIT 1").fetchall()

    def close(self) -> None:
        self._conn.close()
        self._read_conn.close()


def _sqlite_has_column(conn: sqlite3.Connection, column: str) -> bool:
    return any(r[1] == column for r in conn.execute("PRAGMA table_info(audit)"))


def _sqlite_migrate(conn: sqlite3.Connection) -> None:
    """Q26 idempotent migration: add ``hash_version`` to pre-v2 tables (NULL =
    legacy v1 rows). ADD COLUMN is not an UPDATE, so the triggers allow it."""
    if not _sqlite_has_column(conn, "hash_version"):
        conn.execute("ALTER TABLE audit ADD COLUMN hash_version INTEGER")
    if not _sqlite_has_column(conn, "hash_key_id"):
        conn.execute("ALTER TABLE audit ADD COLUMN hash_key_id TEXT")


_PG_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


class PostgresAuditWriter(_BaseAuditWriter):
    """Postgres audit backend (``AUDIT_BACKEND=postgres``).

    Same append-only semantics as the SQLite backend, enforced server-side:
    a plpgsql trigger RAISEs on any UPDATE or DELETE, so even a connection
    holding the app credentials cannot rewrite history (a *superuser* can
    still ``ALTER TABLE ... DISABLE TRIGGER`` — which is exactly the tamper
    scenario the hash chain + the WORM archive cross-check then detect).

    Connection model mirrors the SQLite writer: ONE long-lived connection
    guarded by an RLock (psycopg connections are not safe for concurrent
    cursors across threads). The audit write is off the LLM hot path, so
    serialising it is fine. A dropped connection surfaces loudly — main.py's
    ``_safe_audit_write`` catches the exception and enqueues the row in the
    durable outbox (invariant #4 backstop), exactly as for a failed SQLite
    write.

    ``schema`` exists so the test suite can run each session in a throwaway
    schema on a shared dev Postgres without touching real audit data.
    """

    _ORDER_COL = "row_seq"

    def __init__(self, dsn: str | None = None, schema: str = "public"):
        import psycopg  # lazy: only needed when AUDIT_BACKEND=postgres

        if dsn is None:
            from backend.shared.config import settings

            dsn = settings.POSTGRES_URL
        if not _PG_IDENT_RE.match(schema):
            raise ValueError(f"invalid Postgres schema name: {schema!r}")
        self._schema = schema
        self._lock = threading.RLock()
        # Fail LOUDLY here if Postgres is unreachable: with AUDIT_BACKEND=
        # postgres the gateway must not boot without its audit store
        # (invariant #4 — better no service than a service with no audit).
        self._conn = psycopg.connect(dsn, autocommit=False)
        with self._lock:
            with self._conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                cur.execute(f'SET search_path TO "{schema}"')
                for stmt in _PG_DDL_STATEMENTS:
                    cur.execute(stmt)
            self._conn.commit()
        # M-13: reads (the audit page, chain verification, archival) get their
        # OWN connection and lock. Sharing the writer's meant a full-chain
        # verify — polled every 60 s per open auditor tab — held the lock for
        # the whole fetch, and every audit write (one per gateway request,
        # invariant #4) queued behind it.
        self._read_lock = threading.Lock()
        self._read_conn = psycopg.connect(dsn, autocommit=False)
        with self._read_conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{schema}"')
        self._read_conn.commit()

    @staticmethod
    def _translate(sql: str) -> str:
        # The shared base class writes portable SQL with ``?`` placeholders
        # (the SQLite paramstyle); psycopg uses ``%s``. The audit SQL never
        # contains a literal '?' so plain replace is safe.
        return sql.replace("?", "%s")

    def _fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._read_lock:
            try:
                with self._read_conn.cursor() as cur:
                    cur.execute(self._translate(sql), params)
                    rows = cur.fetchall()
                # End the implicit read transaction so we never hold an old
                # snapshot (and an aborted tx can't poison later statements).
                self._read_conn.commit()
                return rows
            except Exception:
                self._read_conn.rollback()
                raise

    def _append_chained(self, build: Callable[[str], tuple]) -> None:
        # A transaction-scoped advisory lock serialises every writer on this
        # schema's chain — across connections, processes and hosts — and is
        # released by COMMIT/ROLLBACK. Under READ COMMITTED each statement
        # takes a fresh snapshot, so the tail SELECT after the lock sees the
        # previous holder's committed row.
        with self._lock:
            try:
                with self._conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (f"patentmind.audit_chain:{self._schema}",),
                    )
                    cur.execute(self._tail_sql())
                    tail = cur.fetchone()
                    cur.execute(self._translate(_INSERT_SQL), build(tail[0] if tail else ""))
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def read_all_rows(self) -> list[dict[str, Any]]:
        """Insertion-ordered chain rows, fetched under a READ ONLY transaction.

        Defence in depth mirroring the SQLite archiver's ``mode=ro`` URI: the
        archival read path physically cannot mutate the audit table even if a
        bug ever routed a write through it.
        """
        cols = [c.strip() for c in _VERIFY_COLS.split(",")]
        sql = f"SELECT {_VERIFY_COLS} FROM audit ORDER BY {self._ORDER_COL} ASC"  # noqa: S608
        with self._read_lock:
            try:
                with self._read_conn.cursor() as cur:
                    # psycopg (non-autocommit) opens the transaction implicitly
                    # on first execute; SET TRANSACTION must be its first
                    # statement, which this is.
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute(sql)
                    rows = cur.fetchall()
                self._read_conn.commit()
            except Exception:
                self._read_conn.rollback()
                raise
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def ping(self) -> None:
        """Readiness (OBS-9): the write connection answers (see AuditWriter.ping)."""
        with self._lock:
            try:
                with self._conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchall()
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        self._conn.close()
        self._read_conn.close()


def _make_writer() -> _BaseAuditWriter:
    from backend.shared.config import settings

    if settings.AUDIT_BACKEND == "postgres":
        return PostgresAuditWriter()
    return AuditWriter()


writer = _make_writer()


def read_live_rows() -> list[dict[str, Any]]:
    """Read every audit row in insertion order for the WORM archiver.

    Backend-aware single entry point so ``audit_archive.py`` never needs to
    know which store is live:

      * **sqlite** — opens a fresh, short-lived connection in URI read-only
        mode (``mode=ro``) against ``config.AUDIT_DB_PATH``. This module-level
        path lookup is lazy so conftest/tests that monkeypatch the path are
        honoured, and the ro mode means the archiver physically cannot mutate
        the live log (defence in depth on top of the append-only triggers).
      * **postgres** — delegates to the live writer's :meth:`read_all_rows`,
        which wraps the fetch in a ``READ ONLY`` transaction for the same
        guarantee.
    """
    from backend.shared import config

    if config.settings.AUDIT_BACKEND == "postgres":
        return writer.read_all_rows()

    path = Path(config.AUDIT_DB_PATH)
    if not path.exists():
        return []
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        # A file not yet opened by a v2 writer lacks hash_version (read-only
        # connection: no migration here) — select NULL so rows read as v1.
        cols = _VERIFY_COLS
        if not _sqlite_has_column(conn, "hash_version"):
            cols = cols.replace("hash_version", "NULL AS hash_version", 1)
        if not _sqlite_has_column(conn, "hash_key_id"):
            cols = cols.replace("hash_key_id", "NULL AS hash_key_id")
        cur = conn.execute(
            f"SELECT {cols} FROM audit ORDER BY rowid ASC"  # noqa: S608
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    finally:
        conn.close()
