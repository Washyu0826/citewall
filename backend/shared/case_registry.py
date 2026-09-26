"""Server-side case registry — the ONE source of a case's security level (Q15/Q22).

Confidentiality is a property of the CASE, decided on the server, never
inferred from how someone typed the case_id. The registry is a JSON file
(``settings.CASE_REGISTRY_PATH``, default ``data/case_registry.json``)::

    {
      "cases":    {"CASE-2025-001": "public", "CASE-2025-009": "confidential"},
      "patterns": {"CASE-DEMO-*": "public"}
    }

Resolution (fail-closed):

1. A case_id ending in ``-CONF`` is ALWAYS confidential (legacy signal kept as
   an extra guard — it can only make a case stricter, never looser).
2. An exact entry in ``cases`` wins, then the first matching glob in
   ``patterns`` (``fnmatch``, case-sensitive).
3. Anything else — unregistered, empty, unreadable registry — is
   ``confidential``: an unknown case must never be sent to a cloud model.

Marking a case: add it to ``cases`` with ``"public"`` or ``"confidential"``
(or another level listed in ``LOCAL_LLM_FOR_SECURITY_LEVELS``). The file is
re-read automatically when its mtime changes, so no restart is needed.

Q27 admin writes (``upsert_case`` / ``deactivate_case``, used by the
``/v1/admin/cases`` API) store an entry as an object::

    "CASE-2026-042": {"level": "confidential", "active": true, "note": "...",
                      "updated_by": "carol", "updated_at": "2026-09-26T..."}

Plain-string entries (hand edits, older files) stay valid. A deactivated case
resolves to ``confidential`` — it does NOT fall through to a public pattern.

Storage choice: the JSON file stays the single store, written with an
in-process lock + write-to-temp + ``os.replace`` (atomic on the same volume).
Rationale: one gateway process on one on-prem box (Q22), rare admin writes,
and the file must remain hand-editable, diffable and backed up with the rest
of ``data/``; a second store (sqlite) would split the source of truth that
``security_level_for_case`` reads. Every write re-reads the file first, so a
concurrent hand edit is merged, not clobbered. Multi-replica deployments need
a shared DB-backed store instead.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.shared.config import settings

logger = logging.getLogger(__name__)

CONFIDENTIAL = "confidential"
PUBLIC = "public"

_lock = threading.Lock()
_write_lock = threading.Lock()
_cache: dict = {"path": None, "mtime": None, "cases": {}, "patterns": []}


def valid_levels() -> set[str]:
    return {PUBLIC, *settings.LOCAL_LLM_FOR_SECURITY_LEVELS}


def _entry_level(value: Any) -> str | None:
    """Effective level of a stored entry; None if inactive (→ confidential)."""
    if isinstance(value, dict):
        if value.get("active", True) is False:
            return None
        return str(value.get("level", CONFIDENTIAL)).lower()
    return str(value).lower()


def _load(path: Path) -> tuple[dict[str, str | None], list[tuple[str, str]]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    cases = {str(k): _entry_level(v) for k, v in (data.get("cases") or {}).items()}
    patterns = [(str(k), str(v).lower()) for k, v in (data.get("patterns") or {}).items()]
    return cases, patterns


def _registry() -> tuple[dict[str, str], list[tuple[str, str]]]:
    path = Path(settings.CASE_REGISTRY_PATH)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}, []  # no registry => every case is confidential
    with _lock:
        if _cache["path"] != str(path) or _cache["mtime"] != mtime:
            try:
                cases, patterns = _load(path)
            except (OSError, ValueError, AttributeError) as exc:
                logger.error(
                    "case registry %s unreadable (%s) — treating every case as confidential",
                    path,
                    exc.__class__.__name__,
                )
                cases, patterns = {}, []
            _cache.update(path=str(path), mtime=mtime, cases=cases, patterns=patterns)
        return _cache["cases"], _cache["patterns"]


def security_level_for_case(case_id: str | None) -> str:
    """Return the case's security level; unknown cases are confidential."""
    if not case_id:
        return CONFIDENTIAL
    if case_id.upper().endswith("-CONF"):
        return CONFIDENTIAL
    cases, patterns = _registry()
    if case_id in cases:
        # Exact entry wins — including a DEACTIVATED one (None), which must
        # stay confidential rather than fall through to a public pattern.
        return cases[case_id] or CONFIDENTIAL
    level = next((lvl for pat, lvl in patterns if fnmatch.fnmatchcase(case_id, pat)), None)
    return level or CONFIDENTIAL


def is_confidential(case_id: str | None) -> bool:
    return security_level_for_case(case_id) in settings.LOCAL_LLM_FOR_SECURITY_LEVELS


# --- Q27 admin read/write --------------------------------------------------


class RegistryError(ValueError):
    """Invalid admin request (unknown level, duplicate create, missing case)."""


def _read_raw(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise RegistryError("case registry file is not a JSON object")
    data.setdefault("cases", {})
    data.setdefault("patterns", {})
    return data


def _normalise(case_id: str, value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "case_id": case_id,
            "level": str(value.get("level", CONFIDENTIAL)).lower(),
            "active": value.get("active", True) is not False,
            "note": value.get("note", ""),
            "updated_by": value.get("updated_by"),
            "updated_at": value.get("updated_at"),
        }
    return {
        "case_id": case_id,
        "level": str(value).lower(),
        "active": True,
        "note": "",
        "updated_by": None,
        "updated_at": None,
    }


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".case_registry.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    with _lock:
        _cache["mtime"] = None  # force the resolver to re-read on next call


def list_cases() -> dict[str, Any]:
    """All explicit entries (normalised) + the read-only glob patterns."""
    data = _read_raw(Path(settings.CASE_REGISTRY_PATH))
    cases = [_normalise(k, v) for k, v in sorted(data["cases"].items())]
    patterns = [{"pattern": k, "level": str(v).lower()} for k, v in data["patterns"].items()]
    return {"cases": cases, "patterns": patterns, "levels": sorted(valid_levels())}


def get_case(case_id: str) -> dict[str, Any] | None:
    data = _read_raw(Path(settings.CASE_REGISTRY_PATH))
    if case_id not in data["cases"]:
        return None
    return _normalise(case_id, data["cases"][case_id])


def upsert_case(
    case_id: str, level: str, *, actor: str, note: str | None = None, create: bool
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Create (``create=True``, must not exist) or update a case's level.
    Returns ``(before, after)``; ``before`` is None on create. Updating a
    deactivated case reactivates it."""
    level = (level or "").strip().lower()
    if level not in valid_levels():
        raise RegistryError(f"unknown security level {level!r}")
    case_id = (case_id or "").strip()
    if not case_id or len(case_id) > 128:
        raise RegistryError("case_id is required (max 128 chars)")
    path = Path(settings.CASE_REGISTRY_PATH)
    with _write_lock:
        data = _read_raw(path)
        existing = data["cases"].get(case_id)
        if create and existing is not None:
            raise RegistryError(f"case {case_id!r} already registered")
        if not create and existing is None:
            raise RegistryError(f"case {case_id!r} is not registered")
        before = None if existing is None else _normalise(case_id, existing)
        entry = {
            "level": level,
            "active": True,
            "note": (note if note is not None else (before or {}).get("note", ""))[:500],
            "updated_by": actor,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        data["cases"][case_id] = entry
        _atomic_write(path, data)
    return before, _normalise(case_id, entry)


def deactivate_case(case_id: str, *, actor: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mark a case inactive (never deleted — the history stays in the file and
    the audit log). An inactive case resolves to confidential."""
    path = Path(settings.CASE_REGISTRY_PATH)
    with _write_lock:
        data = _read_raw(path)
        existing = data["cases"].get(case_id)
        if existing is None:
            raise RegistryError(f"case {case_id!r} is not registered")
        before = _normalise(case_id, existing)
        entry = {
            "level": before["level"],
            "active": False,
            "note": before["note"],
            "updated_by": actor,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        data["cases"][case_id] = entry
        _atomic_write(path, data)
    return before, _normalise(case_id, entry)
