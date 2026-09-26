"""Deadline calculation (Q17).

Three core requirements:
    1. Per-jurisdiction rules (TW vs US vs JP start counting differently).
    2. Calendar-version locking — recompute uses the same holiday version
       so re-running 6 months later doesn't yield a different answer.
    3. Multi-timezone: mailing date in sender's TZ, deadline in case TZ.

Holiday calendars are CLIENT-UPDATABLE + VERSIONED. They live as
``data/calendars/<jurisdiction>_<version>.json`` (schema below) and are loaded
+ cached on first use. The hard-coded ``_FALLBACK_HOLIDAYS`` dict below is the
safety net: when no JSON file is present (fresh checkout / absent data dir / CI)
the loader degrades to it so nothing ever breaks. This mirrors how the masking
layer externalises per-tenant dictionaries (data/tenant_dicts/<id>.json with a
hard-coded TENANT_DICTIONARIES fallback).

Calendar JSON schema::

    {
      "jurisdiction": "TW",
      "version": "2025.1",
      "holidays": { "2025-01-01": "元旦", ... },
      "workdays": { "2026-02-14": "春节调休上班" },  # optional: make-up WORKING
                                                    # weekends (CN 调休) — no roll
      "metadata": { "verified": true, "sources": ["https://..."] }  # optional
    }

A corrected calendar is published as a NEW revision ("2026.2"), never by
editing a released one; ``calendar_version="auto"`` picks the highest revision
per year.

Calendar-version locking invariant: the same ``(jurisdiction, version)`` ALWAYS
resolves to the same holiday set (the file is the authoritative source; the
hard-coded dict is a byte-for-byte mirror for the shipped 2025.1 versions). A
requested version with NO file AND no hard-coded entry resolves to an EMPTY
calendar plus a LOUD warning in the returned dict — never a silently-wrong date.

POC jurisdictions: TW, US, JP, EP, CN, KR (the EP/CN/KR rules are documented
approximations — see each rule's inline caveat). Anything else stubs out
(60-day default + warning).
"""

from __future__ import annotations

import calendar
import json
import logging
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.shared.config import DATA_DIR, settings

# calendar_version sentinel: pick each year's calendar automatically.
AUTO_CALENDAR = "auto"

logger = logging.getLogger(__name__)

# Where versioned calendars live. Override-able for tests.
CALENDARS_DIR: Path = DATA_DIR / "calendars"


# ---------- Hard-coded fallback holiday data (POC: 2025) ----------
#
# This is the SAFETY NET, not the primary source. The loader below prefers the
# JSON file at data/calendars/<jurisdiction>_<version>.json and only falls back
# here when the file is absent / unreadable. Keep this in sync with the shipped
# *_2025.1.json files (they are byte-for-byte mirrors) so version-locking holds
# regardless of whether the data dir is present.
#
# Format: {(jurisdiction, version): {date: name}}
_FALLBACK_HOLIDAYS: dict[tuple[str, str], dict[date, str]] = {
    ("TW", "2025.1"): {
        date(2025, 1, 1): "元旦",
        date(2025, 1, 27): "農曆除夕（補假）",
        date(2025, 1, 28): "農曆除夕",
        date(2025, 1, 29): "春節初一",
        date(2025, 1, 30): "春節初二",
        date(2025, 1, 31): "春節初三",
        date(2025, 2, 28): "和平紀念日",
        date(2025, 4, 3): "兒童節（補假）",
        date(2025, 4, 4): "兒童節 / 清明",
        date(2025, 5, 1): "勞動節",
        date(2025, 5, 30): "端午節（補假）",
        date(2025, 5, 31): "端午節",
        date(2025, 9, 29): "中秋節（補假）",
        date(2025, 10, 6): "中秋節",
        date(2025, 10, 10): "國慶日",
    },
    ("US", "2025.1"): {
        date(2025, 1, 1): "New Year's Day",
        date(2025, 1, 20): "MLK Day",
        date(2025, 2, 17): "Presidents' Day",
        date(2025, 5, 26): "Memorial Day",
        date(2025, 6, 19): "Juneteenth",
        date(2025, 7, 4): "Independence Day",
        date(2025, 9, 1): "Labor Day",
        date(2025, 10, 13): "Columbus Day",
        date(2025, 11, 11): "Veterans Day",
        date(2025, 11, 27): "Thanksgiving",
        date(2025, 12, 25): "Christmas",
    },
    # JP fallback — abbreviated mirror of JP_2025.1.json (key dates only). The
    # JSON file is authoritative; this guarantees JP still resolves on a fresh
    # checkout with no data dir.
    ("JP", "2025.1"): {
        date(2025, 1, 1): "元日",
        date(2025, 1, 2): "年始休 (JPO closed)",
        date(2025, 1, 3): "年始休 (JPO closed)",
        date(2025, 1, 13): "成人の日",
        date(2025, 2, 11): "建国記念の日",
        date(2025, 2, 23): "天皇誕生日",
        date(2025, 2, 24): "天皇誕生日 振替休日",
        date(2025, 3, 20): "春分の日",
        date(2025, 4, 29): "昭和の日",
        date(2025, 5, 3): "憲法記念日",
        date(2025, 5, 4): "みどりの日",
        date(2025, 5, 5): "こどもの日",
        date(2025, 5, 6): "こどもの日 振替休日",
        date(2025, 7, 21): "海の日",
        date(2025, 8, 11): "山の日",
        date(2025, 9, 15): "敬老の日",
        date(2025, 9, 23): "秋分の日",
        date(2025, 10, 13): "スポーツの日",
        date(2025, 11, 3): "文化の日",
        date(2025, 11, 23): "勤労感謝の日",
        date(2025, 11, 24): "勤労感謝の日 振替休日",
        date(2025, 12, 29): "年末休 (JPO closed)",
        date(2025, 12, 30): "年末休 (JPO closed)",
        date(2025, 12, 31): "年末休 (JPO closed)",
    },
    # EP fallback — byte-for-byte mirror of EP_2025.1.json. APPROXIMATE EPO
    # closure days (see the JSON's source note + the EP RULES caveat).
    ("EP", "2025.1"): {
        date(2025, 1, 1): "New Year's Day (EPO closed, approx.)",
        date(2025, 4, 18): "Good Friday (EPO closed, approx.)",
        date(2025, 4, 21): "Easter Monday (EPO closed, approx.)",
        date(2025, 5, 1): "Labour Day (EPO closed, approx.)",
        date(2025, 5, 8): "Liberation Day (NL, EPO closed, approx.)",
        date(2025, 5, 29): "Ascension Day (EPO closed, approx.)",
        date(2025, 6, 9): "Whit Monday (EPO closed, approx.)",
        date(2025, 10, 3): "German Unity Day (EPO closed, approx.)",
        date(2025, 12, 24): "Christmas Eve (EPO closed, approx.)",
        date(2025, 12, 25): "Christmas Day (EPO closed, approx.)",
        date(2025, 12, 26): "Boxing Day (EPO closed, approx.)",
        date(2025, 12, 31): "New Year's Eve (EPO closed, approx.)",
    },
    # CN fallback — byte-for-byte mirror of CN_2025.1.json. 国务院 statutory
    # public holidays incl. the 春节 + 国庆/中秋 golden weeks.
    ("CN", "2025.1"): {
        date(2025, 1, 1): "元旦",
        date(2025, 1, 28): "春节(除夕)",
        date(2025, 1, 29): "春节(初一)",
        date(2025, 1, 30): "春节(初二)",
        date(2025, 1, 31): "春节(初三)",
        date(2025, 2, 1): "春节",
        date(2025, 2, 2): "春节",
        date(2025, 2, 3): "春节",
        date(2025, 2, 4): "春节",
        date(2025, 4, 4): "清明节",
        date(2025, 5, 1): "劳动节",
        date(2025, 5, 2): "劳动节",
        date(2025, 5, 3): "劳动节",
        date(2025, 5, 4): "劳动节",
        date(2025, 5, 5): "劳动节",
        date(2025, 5, 31): "端午节",
        date(2025, 6, 1): "端午节",
        date(2025, 6, 2): "端午节",
        date(2025, 10, 1): "国庆节",
        date(2025, 10, 2): "国庆节",
        date(2025, 10, 3): "国庆节",
        date(2025, 10, 4): "国庆节",
        date(2025, 10, 5): "国庆节",
        date(2025, 10, 6): "中秋节",
        date(2025, 10, 7): "国庆节",
        date(2025, 10, 8): "国庆节",
    },
    # KR fallback — byte-for-byte mirror of KR_2025.1.json. 공휴일 incl. the
    # 설날 + 추석 three-day blocks and 대체공휴일 substitutions.
    ("KR", "2025.1"): {
        date(2025, 1, 1): "신정",
        date(2025, 1, 28): "설날 연휴",
        date(2025, 1, 29): "설날",
        date(2025, 1, 30): "설날 연휴",
        date(2025, 3, 1): "삼일절",
        date(2025, 3, 3): "삼일절 대체공휴일",
        date(2025, 5, 5): "어린이날 / 부처님오신날",
        date(2025, 5, 6): "대체공휴일",
        date(2025, 6, 6): "현충일",
        date(2025, 8, 15): "광복절",
        date(2025, 10, 3): "개천절",
        date(2025, 10, 6): "추석 연휴",
        date(2025, 10, 7): "추석",
        date(2025, 10, 8): "추석 연휴",
        date(2025, 10, 9): "한글날",
        date(2025, 12, 25): "성탄절",
    },
}


# ---------- Versioned-calendar loader (client-updatable + cached) ----------

# Cache keyed by (jurisdiction, version). A sentinel object distinguishes
# "loaded, resolved to empty" from "not yet loaded" so a genuinely-empty /
# missing calendar is cached (and warned about) exactly once rather than
# re-read on every request.
_calendar_cache: dict[tuple[str, str], dict[date, str]] = {}
_calendar_cache_lock = threading.Lock()
# Records which (jurisdiction, version) resolved with NO source at all, so
# calculate_deadline can surface the loud warning. Populated alongside the
# cache under the same lock.
_calendar_missing: set[tuple[str, str]] = set()


def _calendar_path(jurisdiction: str, version: str) -> Path:
    return CALENDARS_DIR / f"{jurisdiction}_{version}.json"


def _parse_calendar_doc(jurisdiction: str, version: str, doc: object) -> dict[date, str] | None:
    """Validate + parse a loaded calendar JSON document into {date: name}.

    Returns None (caller falls back) on any structural problem. A single bad
    date string is skipped + logged, but does NOT abort the whole calendar."""
    if not isinstance(doc, dict):
        logger.warning(
            "calendar %s_%s: top-level JSON is not an object; ignoring file.",
            jurisdiction,
            version,
        )
        return None
    # Soft-validate the self-describing fields (don't hard-fail on mismatch,
    # but warn — a mislabelled file is a real ops footgun).
    if doc.get("jurisdiction") not in (None, jurisdiction):
        logger.warning(
            "calendar %s_%s: file declares jurisdiction=%r (filename says %r).",
            jurisdiction,
            version,
            doc.get("jurisdiction"),
            jurisdiction,
        )
    if doc.get("version") not in (None, version):
        logger.warning(
            "calendar %s_%s: file declares version=%r (filename says %r).",
            jurisdiction,
            version,
            doc.get("version"),
            version,
        )
    raw = doc.get("holidays")
    if not isinstance(raw, dict):
        logger.warning(
            "calendar %s_%s: 'holidays' is not an object; ignoring file.",
            jurisdiction,
            version,
        )
        return None
    out: dict[date, str] = {}
    for k, name in raw.items():
        try:
            d = date.fromisoformat(k)
        except (TypeError, ValueError):
            logger.warning(
                "calendar %s_%s: skipping un-parseable date key %r.",
                jurisdiction,
                version,
                k,
            )
            continue
        out[d] = str(name)
    return out


def _read_calendar(jurisdiction: str, version: str) -> tuple[dict[date, str], bool]:
    """Resolve a calendar from disk, then hard-coded fallback.

    Returns ``(holidays, found)``. ``found`` is False ONLY when neither a usable
    JSON file NOR a hard-coded fallback exists — that's the "missing version"
    case the caller must warn about. Never raises."""
    path = _calendar_path(jurisdiction, version)
    if path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "calendar %s: failed to read/parse (%s); falling back to hard-coded calendar.",
                path,
                exc,
            )
        else:
            parsed = _parse_calendar_doc(jurisdiction, version, doc)
            if parsed is not None:
                return parsed, True

    fallback = _FALLBACK_HOLIDAYS.get((jurisdiction, version))
    if fallback is not None:
        return dict(fallback), True

    # Neither file nor hard-coded fallback. This is NOT the same as an unknown
    # jurisdiction (handled earlier): it's a known jurisdiction asked for a
    # calendar VERSION we don't have. Empty set + found=False so the caller
    # emits a loud warning rather than silently returning a wrong date.
    return {}, False


def get_holidays(jurisdiction: str, version: str) -> dict[date, str]:
    """Public, cached accessor for a versioned holiday calendar.

    Thread-safe. Same ``(jurisdiction, version)`` ALWAYS returns the same set
    for the process lifetime (version-locking). Call ``reload_calendars()``
    after dropping a new/updated JSON file."""
    key = (jurisdiction, version)
    cached = _calendar_cache.get(key)
    if cached is not None:
        return cached
    with _calendar_cache_lock:
        cached = _calendar_cache.get(key)
        if cached is not None:
            return cached
        holidays, found = _read_calendar(jurisdiction, version)
        _calendar_cache[key] = holidays
        if not found:
            _calendar_missing.add(key)
            logger.warning(
                "calendar %s_%s: NO source (no JSON file, no hard-coded "
                "fallback). Using an EMPTY holiday set — deadline may be wrong. "
                "Load data/calendars/%s_%s.json before relying on this.",
                jurisdiction,
                version,
                jurisdiction,
                version,
            )
    return _calendar_cache[key]


def calendar_is_missing(jurisdiction: str, version: str) -> bool:
    """True iff the requested (jurisdiction, version) resolved with no source.

    Triggers a load (and the warning) if not yet cached."""
    get_holidays(jurisdiction, version)
    return (jurisdiction, version) in _calendar_missing


def deadline_year_is_covered(jurisdiction: str, calendar_version: str, deadline_date: date) -> bool:
    """True iff the loaded calendar covers ``deadline_date``'s year.

    Out-of-band query so callers/tests can branch on the year-boundary
    condition without parsing the warnings list. Mirrors the inline check in
    ``calculate_deadline``: a year is "covered" iff the loaded calendar has at
    least one holiday in it."""
    holidays = get_holidays(jurisdiction, calendar_version)
    return any(h.year == deadline_date.year for h in holidays)


def reload_calendars() -> None:
    """Drop the calendar cache so freshly-dropped JSON files are picked up.

    The masking layer has the same per-upload reload story. Cheap; calendars
    are small."""
    with _calendar_cache_lock:
        _calendar_cache.clear()
        _calendar_missing.clear()
        _workdays_cache.clear()


# Backwards-compatible alias. Older code / tests referenced the module-level
# ``HOLIDAYS`` dict directly. It now maps to the hard-coded fallback (the
# authoritative source is the JSON loader via get_holidays()).
HOLIDAYS = _FALLBACK_HOLIDAYS


# ---------- Pluggable HolidayProvider abstraction (Agent C) ----------
#
# The module-level loader above (get_holidays / _read_calendar / _calendar_cache)
# IS, in effect, a caching provider with a bundled fallback. Agent C formalises
# that as a swappable HolidayProvider so a cron job (or, eventually, a live
# remote feed) can supply calendars without touching the deadline maths.
#
# Layering rule: the providers are an ADDITIVE wrapper. ``get_holidays`` and
# ``calculate_deadline`` keep their exact prior behaviour by defaulting to the
# StaticBundledProvider, which delegates to ``_read_calendar`` — so every
# existing test stays green. Swap the active provider via ``set_holiday_provider``
# or the HOLIDAY_SOURCE env flag; ``reload_calendars()`` drops both the
# module-level cache AND any provider-internal cache.
#
# Resolution contract every provider obeys:
#   resolve(jurisdiction, version) -> (holidays: dict[date,str], found: bool)
#   ``found`` is False ONLY when the provider has NO source for that
#   (jurisdiction, version) — the "missing calendar" case the caller must warn
#   about. A provider MUST NOT raise for a merely-missing calendar; it returns
#   ({}, False). It MAY raise for a genuinely broken backend (the CachingHoliday
#   Provider swallows NotImplementedError specifically, so a stubbed remote
#   backend degrades to inert rather than exploding).


class HolidayProvider(ABC):
    """A source of versioned holiday calendars, keyed by (jurisdiction, version)."""

    @abstractmethod
    def resolve(self, jurisdiction: str, version: str) -> tuple[dict[date, str], bool]:
        """Return ``(holidays, found)``. Never raise for a merely-missing
        calendar — return ``({}, False)`` instead."""
        raise NotImplementedError

    # Deliberately a concrete no-op, not @abstractmethod: reload is an OPTIONAL
    # hook — only caching providers need it, and forcing every provider to
    # implement an empty override would be noise (B027 suppressed by design).
    def reload(self) -> None:  # noqa: B027  # pragma: no cover - default no-op
        """Drop any provider-internal cache. Overridden by caching providers."""


class StaticBundledProvider(HolidayProvider):
    """Default, hermetic provider: shipped JSON files in data/calendars/ with the
    hard-coded ``_FALLBACK_HOLIDAYS`` mirror as the safety net. This is exactly
    the behaviour the module shipped with — it just delegates to ``_read_calendar``
    so version-locking + the file/fallback agreement are unchanged."""

    def resolve(self, jurisdiction: str, version: str) -> tuple[dict[date, str], bool]:
        return _read_calendar(jurisdiction, version)


class JsonFileProvider(HolidayProvider):
    """File-only provider: reads ONLY ``<dir>/<jurisdiction>_<version>.json`` with
    NO hard-coded fallback. Use this when a cron job (scripts/fetch_holidays.py)
    owns the calendars and you want a missing/clobbered file to surface loudly
    rather than be papered over by the bundled mirror. Still fully offline."""

    def __init__(self, calendars_dir: Path | None = None):
        self._dir = calendars_dir  # None -> read the live module CALENDARS_DIR

    def _path(self, jurisdiction: str, version: str) -> Path:
        base = self._dir if self._dir is not None else CALENDARS_DIR
        return base / f"{jurisdiction}_{version}.json"

    def resolve(self, jurisdiction: str, version: str) -> tuple[dict[date, str], bool]:
        path = self._path(jurisdiction, version)
        if not path.exists():
            return {}, False
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("JsonFileProvider: failed to read %s (%s).", path, exc)
            return {}, False
        parsed = _parse_calendar_doc(jurisdiction, version, doc)
        if parsed is None:
            return {}, False
        return parsed, True


class RemoteHolidayProvider(HolidayProvider):
    """STUB. Would pull live official feeds (data.gov.tw for TW, the USPTO
    calendar for US, etc.) on demand. INTENTIONALLY unimplemented: enabling it is
    safe-but-inert because the CachingHolidayProvider that wraps it swallows the
    NotImplementedError and degrades to its fallback provider. The test suite
    NEVER instantiates this against the network.

    Real impl belongs in (or shares code with) scripts/fetch_holidays.py, which
    already knows how to fetch + parse each jurisdiction. This class would call
    that producer and return the parsed calendar, caching to data/calendars/ so
    the offline providers pick it up. Until then it raises so nobody ships a
    silent live dependency by accident."""

    def __init__(self, source: str = "remote"):
        self.source = source

    def resolve(self, jurisdiction: str, version: str) -> tuple[dict[date, str], bool]:
        raise NotImplementedError(
            "RemoteHolidayProvider is a stub. Wire scripts/fetch_holidays.py to "
            "pull from data.gov.tw (TW) / USPTO (US) and write data/calendars/. "
            "Until then run with HOLIDAY_SOURCE=bundled (the default)."
        )


class CachingHolidayProvider(HolidayProvider):
    """Thread-safe, version-locked cache in front of an inner provider, with an
    optional fallback provider used when the inner provider raises or returns
    not-found.

    Two safety properties:
      1. Version locking: the same (jurisdiction, version) always returns the
         same object for the provider's lifetime (until ``reload()``).
      2. Safe-but-inert remote: if the inner provider raises NotImplementedError
         (the RemoteHolidayProvider stub) — or any other exception — the cache
         logs it once and delegates to ``fallback`` (default: a
         StaticBundledProvider). So flipping HOLIDAY_SOURCE=remote can NEVER take
         the engine down; it quietly keeps using the bundled calendars."""

    def __init__(
        self,
        inner: HolidayProvider,
        fallback: HolidayProvider | None = None,
    ):
        self._inner = inner
        self._fallback = fallback if fallback is not None else StaticBundledProvider()
        self._cache: dict[tuple[str, str], tuple[dict[date, str], bool]] = {}
        self._lock = threading.Lock()

    def resolve(self, jurisdiction: str, version: str) -> tuple[dict[date, str], bool]:
        key = (jurisdiction, version)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            result = self._resolve_uncached(jurisdiction, version)
            self._cache[key] = result
            return result

    def _resolve_uncached(self, jurisdiction: str, version: str) -> tuple[dict[date, str], bool]:
        try:
            holidays, found = self._inner.resolve(jurisdiction, version)
        except NotImplementedError:
            logger.warning(
                "CachingHolidayProvider: inner provider %s is a stub for %s_%s; "
                "degrading to fallback %s (safe-but-inert).",
                type(self._inner).__name__,
                jurisdiction,
                version,
                type(self._fallback).__name__,
            )
            return self._fallback.resolve(jurisdiction, version)
        except Exception as exc:  # noqa: BLE001 — defensive: never let a backend kill the engine
            logger.warning(
                "CachingHolidayProvider: inner provider %s raised for %s_%s (%s); "
                "degrading to fallback %s.",
                type(self._inner).__name__,
                jurisdiction,
                version,
                exc,
                type(self._fallback).__name__,
            )
            return self._fallback.resolve(jurisdiction, version)
        if found:
            return holidays, True
        # Inner had no source — try the fallback before giving up.
        return self._fallback.resolve(jurisdiction, version)

    def reload(self) -> None:
        with self._lock:
            self._cache.clear()
        self._inner.reload()
        self._fallback.reload()


def _build_provider_for_source(source: str) -> HolidayProvider:
    """Map the HOLIDAY_SOURCE flag to a concrete (cached) provider.

    Every branch is wrapped in CachingHolidayProvider so version-locking +
    safe-but-inert degradation hold uniformly. ``bundled`` returns the plain
    StaticBundledProvider behaviour (the historical default)."""
    src = (source or "bundled").lower()
    if src == "jsonfile":
        return CachingHolidayProvider(JsonFileProvider())
    if src == "remote":
        # Remote inner, bundled fallback -> safe-but-inert until the stub lands.
        return CachingHolidayProvider(RemoteHolidayProvider(), fallback=StaticBundledProvider())
    # default / "bundled"
    return CachingHolidayProvider(StaticBundledProvider())


# The active provider. Defaults from HOLIDAY_SOURCE but is overridable at runtime
# (set_holiday_provider) for tests / ops. NOTE: get_holidays() above is the
# historical entry point and intentionally keeps using the module-level
# _read_calendar cache so its byte-for-byte behaviour + identity-caching
# (test_get_holidays_version_locked_and_cached) are preserved. The provider is
# consulted by the NEW strict/lenient v2 surface below. They share the same
# underlying data, so results agree.
_active_provider: HolidayProvider = _build_provider_for_source(
    getattr(settings, "HOLIDAY_SOURCE", "bundled")
)


def get_holiday_provider() -> HolidayProvider:
    return _active_provider


def set_holiday_provider(provider: HolidayProvider) -> None:
    """Swap the active provider (tests / ops). Also drops the module-level
    loader cache so the next get_holidays() observes a consistent world."""
    global _active_provider
    _active_provider = provider
    reload_calendars()


# Wire the provider into reload so a single reload_calendars() clears everything.
_reload_calendars_base = reload_calendars


def reload_calendars() -> None:  # type: ignore[no-redef]
    """Drop ALL holiday caches: the module-level loader cache AND the active
    provider's internal cache. Call after dropping a new/updated JSON file."""
    _reload_calendars_base()
    try:
        _active_provider.reload()
    except Exception:  # noqa: BLE001 — reload must never raise
        logger.exception("reload_calendars: provider reload failed (ignored).")


# ---------- Observed-holiday shifting (Agent C) ----------
#
# Many calendars publish a fixed-date holiday and a SEPARATE "observed" day when
# that date lands on a weekend. The US OPM rule shifts Sat->Fri and Sun->Mon.
# JP (振替休日) and KR (대체공휴일) shift a Sunday holiday to the next non-holiday
# weekday. The shipped JSON calendars ALREADY bake the observed days in (e.g. JP
# 2025-02-24 振替休日, KR 2025-03-03 대체공휴일), so the roll-forward engine needs no
# special-casing. These helpers are exposed for calendar PRODUCERS / validators
# (scripts/fetch_holidays.py) and are unit-tested table-driven.


def observed_us(holiday: date) -> date:
    """US OPM in-lieu-of rule: a holiday on Saturday is observed the preceding
    Friday; on Sunday, the following Monday. Weekday holidays are unchanged."""
    if holiday.weekday() == 5:  # Saturday -> Friday
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:  # Sunday -> Monday
        return holiday + timedelta(days=1)
    return holiday


def observed_substitute_next_weekday(holiday: date, existing: set[date]) -> date:
    """JP 振替休日 / KR 대체공휴일 style: if ``holiday`` falls on a Sunday (or on a day
    already in ``existing``, i.e. overlapping another holiday), the substitute is
    the next day that is neither a weekend nor already a holiday. Returns the
    holiday unchanged when no substitution is required."""
    if holiday.weekday() != 6 and holiday not in existing:
        return holiday
    d = holiday + timedelta(days=1)
    for _ in range(_MAX_ROLL_DAYS):
        if d.weekday() < 5 and d not in existing:
            return d
        d += timedelta(days=1)
    raise ValueError("no substitute weekday within bound — bad calendar")


# ---------- Typed errors + strict API (Agent C) ----------


class DeadlineError(ValueError):
    """Base class for all deadline-engine errors. Subclasses ValueError so
    existing ``except ValueError`` handlers keep catching it."""


class UnknownJurisdictionError(DeadlineError):
    """Requested a jurisdiction with no rule. The lenient calculate_deadline
    returns the 60-day naive stub instead of raising this."""


class InvalidReceivedDateError(DeadlineError):
    """received_date is not a timezone-aware datetime (naive datetimes are
    rejected: an ambiguous wall-clock instant can shift the case-local date)."""


class CalendarRangeError(DeadlineError):
    """The computed deadline involves a year the loaded calendar can't cover, or
    the calendar version has no source at all. The lenient path WARNS instead."""


def calculate_deadline_strict(
    received_date: datetime,
    jurisdiction: str = "TW",
    calendar_version: str | None = AUTO_CALENDAR,
    **kwargs,
) -> dict:
    """Validating wrapper around ``calculate_deadline`` (``kwargs`` are passed
    through: applicant_domestic / oa_sequence / service_date / oa_text).

    Same return dict as the lenient function on success. Differs in that the
    conditions the lenient path merely WARNS about become RAISED, typed errors:

      * unknown jurisdiction         -> UnknownJurisdictionError
      * naive (tz-unaware) datetime  -> InvalidReceivedDateError
      * missing calendar version     -> CalendarRangeError
      * deadline lands in / rolls into an uncovered year -> CalendarRangeError

    Use this on a write path where a wrong-but-silent deadline is unacceptable;
    use the lenient ``calculate_deadline`` on a best-effort display path that
    must always return SOMETHING (it surfaces the same problems via warnings)."""
    if received_date.tzinfo is None or received_date.utcoffset() is None:
        raise InvalidReceivedDateError(
            "received_date must be timezone-aware (got a naive datetime). "
            "Attach the sender's tz so the case-local date is unambiguous."
        )
    if jurisdiction not in RULES:
        raise UnknownJurisdictionError(
            f"Jurisdiction {jurisdiction!r} is not implemented. Supported: "
            f"{', '.join(sorted(RULES))}."
        )
    result = calculate_deadline(received_date, jurisdiction, calendar_version, **kwargs)
    if calendar_version in (None, AUTO_CALENDAR):
        sd = date.fromisoformat(result["statutory_deadline"][:10])
        holidays, label, missing = resolve_calendar(
            jurisdiction, AUTO_CALENDAR, range(sd.year, sd.year + 1)
        )
        if missing or not any(h.year == sd.year for h in holidays):
            raise CalendarRangeError(
                f"No holiday calendar for {jurisdiction} covers the statutory "
                f"deadline {sd}. Load data/calendars/{jurisdiction}_{sd.year}.1.json "
                f"and recompute."
            )
        return result
    if (jurisdiction, calendar_version) in _calendar_missing:
        raise CalendarRangeError(
            f"Holiday calendar {jurisdiction}_{calendar_version} has no source "
            f"(no JSON file, no fallback). Refusing to return a deadline computed "
            f"against an empty calendar. Load data/calendars/"
            f"{jurisdiction}_{calendar_version}.json and retry."
        )
    sd = date.fromisoformat(result["statutory_deadline"][:10])
    if not deadline_year_is_covered(jurisdiction, calendar_version, sd):
        raise CalendarRangeError(
            f"Statutory deadline {sd} falls in a year the loaded calendar "
            f"{jurisdiction}_{calendar_version} does not cover. Load the matching "
            f"year's calendar and recompute."
        )
    return result


# ---------- Rule specs ----------


@dataclass(frozen=True)
class JurisdictionRule:
    name: str
    response_days: int  # statutory days from start_date
    excludes_weekends: bool
    excludes_holidays: bool
    timezone_name: str
    extension_days: int | None  # e.g. US +3 month; TW one-off extension
    # Statutory period expressed in CALENDAR MONTHS. When set it wins over
    # ``response_days`` (kept as the rough day-equivalent for display/legacy):
    # "3 months" from Jan 31 ends Apr 30, not Jan 31 + 90 days = May 1.
    response_months: int | None = None
    # Which event the period runs from. "mailing" = the date the notice bears /
    # is dispatched (US 37 CFR 1.134, EPO Rule 126(2) as amended 2023-11-01,
    # JPO 発送日). "service" = the day the applicant is served (TW 送達, KR
    # 통지서 도달, CN 送达). For "service" rules an explicit service date wins;
    # otherwise ``presumed_service_days`` after mailing (CN: +15 days,
    # 专利法实施细则 送达推定) or, failing that, the mailing date + a warning.
    start_event: str = "mailing"
    presumed_service_days: int = 0
    # Q16 JP: domestic applicants get ``response_days`` (60 日); overseas
    # applicants get this many months. Unknown domicile -> the EARLIER value.
    foreign_response_months: int | None = None
    # Q17 CN: 2nd and later 审查意见通知书 get this many months (the first gets
    # ``response_months``). Unknown sequence -> the EARLIER value.
    subsequent_response_months: int | None = None


# Q21: none of these rules has been reviewed by a patent attorney yet. Every
# deadline response carries ``rules_reviewed: False`` so the UI can say so.
RULES_REVIEWED = False


RULES: dict[str, JurisdictionRule] = {
    "TW": JurisdictionRule(
        name="台灣 TIPO 答辯期間",
        response_days=60,  # 兩個月（簡化）
        excludes_weekends=False,  # 週末算入；只有最後一日為假日才順延
        excludes_holidays=False,
        timezone_name="Asia/Taipei",
        extension_days=30,
        response_months=2,  # 二個月，依民法 §121 以月計算
        # Q18: kept at 2 months (conservative); foreign applicants may have 3.
        start_event="service",
    ),
    "US": JurisdictionRule(
        name="USPTO Office Action shortened response",
        response_days=90,  # 3 months shortened
        excludes_weekends=False,
        excludes_holidays=False,
        timezone_name="America/New_York",
        extension_days=90,
        response_months=3,  # 37 CFR 1.134 SSP; MPEP 710.01(a) month counting
    ),
    # JP (JPO) — POC APPROXIMATION, pending attorney confirmation.
    # Basis: a JPO office action (拒絶理由通知) gives a domestic applicant a
    # ~3-month response period; overseas applicants commonly get an extended
    # window. We model the common 3-month (90-day) figure counted from the
    # received/dispatch date in Asia/Tokyo. If the last day falls on a JPO
    # closure day (national holiday, 振替休日, or the 12/29–1/3 year-end break)
    # it rolls to the next business day under 特許法施行規則 practice. The exact
    # start event (dispatch vs deemed-receipt 発送日 +N) and overseas-extension
    # rules MUST be confirmed with a JP attorney before production use.
    # Q16 (2026-09-25): domestic applicant 60 日 from 発送日; overseas
    # applicant 3 months. Unknown domicile -> 60 日 (earlier) + a warning.
    "JP": JurisdictionRule(
        name="JPO 拒絶理由通知 応答期間 (POC approximation)",
        response_days=60,  # domestic 60 日
        excludes_weekends=False,
        excludes_holidays=False,
        timezone_name="Asia/Tokyo",
        extension_days=90,
        foreign_response_months=3,  # 在外者 3 か月
    ),
    # EP (EPO) — POC APPROXIMATION, pending attorney confirmation.
    # Basis: a response to an EPO examining-division communication under
    # Art. 94(3) EPC is set in the communication itself and is conventionally
    # ~4 months from the communication date. We model 4 months as 120 days
    # counted from the communication date in Europe/Berlin (the canonical IANA
    # zone covering the EPO's Munich seat — there is no separate "Europe/Munich"
    # zone). If the last day falls on a weekend or an EPO non-working day it
    # rolls to the next day the EPO is open (Rule 134(1) EPC).
    # CAVEAT 1: the period is a CALENDAR-MONTH count under Rule 131(4) EPC (e.g.
    #   a communication dated the 15th expires on the 15th four months later),
    #   NOT a fixed 120-day count; the 120-day figure is a POC simplification
    #   that the dataclass's day-based schema forces and can be off by 1-2 days.
    # CAVEAT 2: the old "10-day rule" (Rule 126(2) EPC, +10 days for notified
    #   deemed-delivery) was ABOLISHED for documents notified on/after
    #   2023-11-01, so we do NOT add it; pre-2023 communications would need it.
    # The exact start event and any further-processing/extension rights MUST be
    # confirmed with an EP attorney before production use.
    "EP": JurisdictionRule(
        name="EPO Art. 94(3) examination response (POC approximation)",
        response_days=120,  # ~4 months, simplified to fixed days
        excludes_weekends=False,
        excludes_holidays=False,
        timezone_name="Europe/Berlin",  # canonical IANA zone for Munich
        extension_days=60,  # further processing / extension, approx.
        response_months=4,  # Rule 131(4) EPC calendar months (resolves CAVEAT 1)
    ),
    # CN (CNIPA) — POC APPROXIMATION, pending attorney confirmation.
    # Basis: a response to the first Office Action (审查意见通知书) is due ~4
    # months from the 发文日 (issue/dispatch date printed on the notice). We
    # model 4 months as 120 days counted in Asia/Shanghai. Roll forward over
    # weekends + national holidays (incl. the multi-day 春节/国庆 golden weeks).
    # CAVEAT: under 专利法实施细则, the period actually runs from the date of
    #   RECEIPT, which the rules PRESUME to be the 发文日 + 15 days (送达推定).
    #   So a more faithful statutory deadline is closer to 发文日 + 15 + ~120
    #   days. This engine counts from whatever received_date the caller passes;
    #   if the caller passes the 发文日, add the +15-day presumption upstream (or
    #   pass the presumed receipt date). The 15-day presumption is NOT auto-added
    #   here to avoid double-counting when the caller already has the true
    #   receipt date. Confirm with a CN attorney before production use.
    "CN": JurisdictionRule(
        name="CNIPA 审查意见通知书 答复期限 (POC approximation)",
        response_days=120,  # ~4 months from 发文日, simplified
        excludes_weekends=False,
        excludes_holidays=False,
        timezone_name="Asia/Shanghai",
        extension_days=60,
        response_months=4,  # first OA: 4 个月
        # Q17: 2nd and later OAs -> 2 个月; unknown sequence -> 2 (earlier).
        subsequent_response_months=2,
        # Q19: period runs from service, presumed 发文日 + 15 days.
        start_event="service",
        presumed_service_days=15,
    ),
    # KR (KIPO) — POC APPROXIMATION, pending attorney confirmation.
    # Basis: a response to a KIPO office action (의견제출통지서) is conventionally
    # ~2 months from notification for a domestic applicant, extendable on
    # request. We model 2 months as 60 days counted in Asia/Seoul, rolling
    # forward over weekends + national holidays (incl. the 설날/추석 blocks).
    # CAVEAT: the exact start event (notification vs deemed receipt) and the
    #   per-month extension scheme (KIPO grants extensions in monthly tranches)
    #   are simplified; confirm with a KR attorney before production use.
    "KR": JurisdictionRule(
        name="KIPO 의견제출통지서 응답기간 (POC approximation)",
        response_days=60,  # ~2 months, extendable
        excludes_weekends=False,
        excludes_holidays=False,
        timezone_name="Asia/Seoul",
        extension_days=30,
        response_months=2,  # 2 개월
        start_event="service",
    ),
}


_MAX_ROLL_DAYS = 30  # termination guard against a malformed holiday calendar


def add_calendar_months(d: date, months: int) -> date:
    """``d`` + ``months`` calendar months, clamped to the last day of the target
    month when it has no corresponding day (Jan 31 + 1 month = Feb 28/29).

    This is the "corresponding day" rule shared by TW 民法 §121-2, MPEP
    710.01(a) and Rule 131(4) EPC. A fixed day-count approximation of a month
    period can land a day AFTER the true deadline (e.g. US 2025-01-31 + 90 days
    = 2025-05-01, but the 3-month date is 2025-04-30)."""
    total = d.month - 1 + months
    y, m = d.year + total // 12, total % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


_VERSION_RE = re.compile(r"^(\d{4})\.(\d+)$")


def _available_versions(jurisdiction: str) -> list[str]:
    """Every calendar version we have for ``jurisdiction`` (JSON files + the
    hard-coded fallback), e.g. ["2025.1", "2026.1"]."""
    found = {k[1] for k in _FALLBACK_HOLIDAYS if k[0] == jurisdiction}
    if CALENDARS_DIR.exists():
        prefix = f"{jurisdiction}_"
        for p in CALENDARS_DIR.glob(f"{jurisdiction}_*.json"):
            found.add(p.stem[len(prefix) :])
    return sorted(v for v in found if _VERSION_RE.match(v))


def _versions_for_years(jurisdiction: str, years: range) -> dict[int, str]:
    """Pick, per year, the highest-revision calendar keyed to it ("2026.2"
    beats "2026.1"). Years with no calendar are absent."""
    best: dict[int, tuple[int, str]] = {}
    for v in _available_versions(jurisdiction):
        m = _VERSION_RE.match(v)
        y, rev = int(m.group(1)), int(m.group(2))
        if y in years and (y not in best or rev > best[y][0]):
            best[y] = (rev, v)
    return {y: v for y, (_rev, v) in best.items()}


def resolve_calendar(
    jurisdiction: str, calendar_version: str | None, years: range
) -> tuple[dict[date, str], str, bool]:
    """Return ``(holidays, version_label, missing)``.

    * explicit version ("2025.1") -> exactly that calendar (version-locked, as before)
    * ``"auto"`` / None           -> for each year in ``years`` the best calendar
      keyed to that year, merged — so a 2026 deadline is computed against the
      2026 calendar instead of silently against 2025's holidays.
    ``missing`` is True when no calendar source was found at all.
    """
    if calendar_version and calendar_version != AUTO_CALENDAR:
        holidays = get_holidays(jurisdiction, calendar_version)
        return holidays, calendar_version, (jurisdiction, calendar_version) in _calendar_missing
    chosen = sorted(set(_versions_for_years(jurisdiction, years).values()))
    if not chosen:
        return {}, AUTO_CALENDAR, True
    merged: dict[date, str] = {}
    for v in chosen:
        merged.update(get_holidays(jurisdiction, v))
    return merged, "+".join(chosen), False


_workdays_cache: dict[tuple[str, str], frozenset[date]] = {}


def get_workdays(jurisdiction: str, version: str) -> frozenset[date]:
    """Make-up WORKING weekend days (CN 调休上班) from the calendar JSON's
    optional ``"workdays": {"2026-02-14": "春节调休上班", ...}`` key.

    A weekend listed here is a working day: a deadline landing on it does NOT
    roll forward. Only JSON files carry this (no hard-coded fallback); a missing
    key means "no make-up working days"."""
    key = (jurisdiction, version)
    cached = _workdays_cache.get(key)
    if cached is not None:
        return cached
    out: set[date] = set()
    path = _calendar_path(jurisdiction, version)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8")).get("workdays") or {}
        except (OSError, ValueError, AttributeError):
            raw = {}
        for k in raw if isinstance(raw, dict) else ():
            try:
                out.add(date.fromisoformat(k))
            except (TypeError, ValueError):
                logger.warning("calendar %s_%s: skipping bad workday %r.", *key, k)
    result = frozenset(out)
    with _calendar_cache_lock:
        _workdays_cache[key] = result
    return result


def resolve_workdays(
    jurisdiction: str, calendar_version: str | None, years: range
) -> frozenset[date]:
    """Workdays for the same calendar selection ``resolve_calendar`` makes."""
    if calendar_version and calendar_version != AUTO_CALENDAR:
        return get_workdays(jurisdiction, calendar_version)
    out: set[date] = set()
    for v in set(_versions_for_years(jurisdiction, years).values()):
        out |= get_workdays(jurisdiction, v)
    return frozenset(out)


def _is_business_day(d: date, holidays: dict[date, str], workdays: frozenset[date]) -> bool:
    return d not in holidays and (d.weekday() < 5 or d in workdays)


def _next_business_day(
    d: date, holidays: dict[date, str], workdays: frozenset[date] = frozenset()
) -> date:
    for _ in range(_MAX_ROLL_DAYS):
        if _is_business_day(d, holidays, workdays):
            return d
        d += timedelta(days=1)
    raise ValueError(f"no business day within {_MAX_ROLL_DAYS} days — bad holiday calendar")


def _prev_business_day(
    d: date, holidays: dict[date, str], workdays: frozenset[date] = frozenset()
) -> date:
    """Roll BACKWARD to the nearest business day (for the internal-warning
    date, which must never land on/after the statutory deadline)."""
    for _ in range(_MAX_ROLL_DAYS):
        if _is_business_day(d, holidays, workdays):
            return d
        d -= timedelta(days=1)
    raise ValueError(f"no business day within {_MAX_ROLL_DAYS} days — bad holiday calendar")


# ---------- Period / start-event selection (Q16–Q19, 2026-09-25) ----------

_CN_NUMERALS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}  # fmt: skip
_CN_OA_SEQ_RE = re.compile(r"第\s*([一二三四五六七八九十]+|\d+)\s*次\s*(?:审查意见|審查意見)")
# The period the notice itself states: "…发文日起四个月内陈述意见…".
_CN_STATED_PERIOD_RE = re.compile(r"起\s*([一二两兩三四五六]|\d)\s*[个個]?月[内內]")
_CN_MONTH_WORDS = {"一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6}
_SERVICE_LABEL_RE = re.compile(
    r"(?:送達日期|送达日期|送達日|送达日|收文日期|收文日|受領日|도달일자?|"
    r"Date\s+of\s+(?:receipt|service)|Service\s+Date|Received\s+on)\s*[:：]?\s*",
    re.I,
)


def detect_cn_oa_sequence(oa_text: str | None) -> int | None:
    """``第一次/第二次…审查意见通知书`` -> 1/2/…; None when the text doesn't say."""
    if not oa_text:
        return None
    m = _CN_OA_SEQ_RE.search(oa_text)
    if not m:
        return None
    tok = m.group(1)
    if tok.isdigit():
        return int(tok)
    if tok == "十":
        return 10
    if tok.startswith("十"):  # 十一 .. 十九
        return 10 + _CN_NUMERALS.get(tok[1:], 0)
    return _CN_NUMERALS.get(tok)


def extract_service_date(oa_text: str | None) -> date | None:
    """An explicitly labelled service / receipt date (送達日, 收文日, Date of
    receipt …) in the OA text, or None. Never a mailing or filing date."""
    if not oa_text:
        return None
    from backend.ai_engine.oa_analyzer import _date_at_start  # shared date shapes

    for label in _SERVICE_LABEL_RE.finditer(oa_text):
        dt = _date_at_start(oa_text[label.end() : label.end() + 40])
        if dt is not None:
            return dt.date()
    return None


def detect_cn_stated_months(oa_text: str | None) -> int | None:
    """The response period printed on a CN notice ("起四个月内" -> 4), or None."""
    if not oa_text:
        return None
    m = _CN_STATED_PERIOD_RE.search(oa_text)
    if not m:
        return None
    tok = m.group(1)
    return int(tok) if tok.isdigit() else _CN_MONTH_WORDS.get(tok)


def select_period(
    jurisdiction: str,
    *,
    applicant_domestic: bool | None = None,
    oa_sequence: int | None = None,
    stated_months: int | None = None,
) -> tuple[int | None, int | None, str, list[str]]:
    """Return ``(months, days, label, assumptions)`` for the applicable period.

    Exactly one of months/days is set. Unknown facts resolve to the EARLIER
    (safer) period and say so in ``assumptions``."""
    rule = RULES[jurisdiction]
    notes: list[str] = []
    if rule.foreign_response_months:  # JP
        if applicant_domestic is False:
            m = rule.foreign_response_months
            return m, None, f"{m} months (overseas applicant)", notes
        if applicant_domestic is None:
            notes.append(
                f"Applicant domicile unknown — assumed DOMESTIC ({rule.response_days} days, "
                f"the earlier deadline). Overseas applicants have "
                f"{rule.foreign_response_months} months."
            )
        return None, rule.response_days, f"{rule.response_days} days (domestic applicant)", notes
    if rule.subsequent_response_months:  # CN
        if oa_sequence is None and stated_months:
            # The notice prints its own period — more reliable than inferring
            # it from 第N次 (and the only signal when the sequence is absent).
            return stated_months, None, f"{stated_months} months (stated in the notice)", notes
        if oa_sequence == 1:
            m = rule.response_months
            return m, None, f"{m} months (first Office Action)", notes
        m = rule.subsequent_response_months
        if oa_sequence is None:
            notes.append(
                f"Office Action sequence unknown — assumed a 2nd-or-later action ({m} months, "
                f"the earlier deadline). A FIRST 审查意见通知书 has {rule.response_months} months."
            )
            return m, None, f"{m} months (sequence unknown; assumed 2nd+)", notes
        return m, None, f"{m} months (Office Action #{oa_sequence})", notes
    if jurisdiction == "TW":
        notes.append(
            "TW period kept at 2 months (conservative). Applicants without a domicile in "
            "Taiwan may be granted 3 months — check the notice."
        )
    if rule.response_months:
        return rule.response_months, None, f"{rule.response_months} months", notes
    return None, rule.response_days, f"{rule.response_days} days", notes


def select_start_date(
    jurisdiction: str,
    mailing_local: date,
    *,
    service_date: date | None = None,
) -> tuple[date, str, list[str]]:
    """Return ``(start_date, basis, assumptions)`` per the rule's start event."""
    rule = RULES[jurisdiction]
    if rule.start_event != "service":
        return mailing_local, "mailing_date", []
    if service_date is not None:
        return service_date, "service_date", []
    if rule.presumed_service_days:
        start = mailing_local + timedelta(days=rule.presumed_service_days)
        return (
            start,
            "presumed_service",
            [
                f"Service date not supplied — presumed service = mailing date + "
                f"{rule.presumed_service_days} days ({start})."
            ],
        )
    return (
        mailing_local,
        "mailing_date_fallback",
        [
            "Service (送達) date not supplied — counted from the MAILING date instead. The "
            "real deadline runs from service and may be later; enter the service date."
        ],
    )


def calculate_deadline(
    received_date: datetime,
    jurisdiction: str = "TW",
    calendar_version: str | None = AUTO_CALENDAR,
    *,
    applicant_domestic: bool | None = None,
    oa_sequence: int | None = None,
    service_date: date | None = None,
    oa_text: str | None = None,
) -> dict:
    """Returns dict with deadline info.

    ``received_date`` is the MAILING / issue date of the notice (what the OA
    text prints). The period then runs from the rule's start event (Q19):
    an explicit ``service_date`` (or one labelled in ``oa_text``) for
    service-based jurisdictions, else a presumed service date (CN +15 days),
    else the mailing date with a warning. ``applicant_domestic`` (JP, Q16) and
    ``oa_sequence`` (CN, Q17; auto-detected from ``oa_text``) pick the period;
    unknown facts resolve to the EARLIER deadline and are listed in
    ``assumptions`` (and ``warnings``).

    Q17 invariants:
      - Compute in case_tz, returns ISO with explicit offset.
      - If statutory deadline lands on weekend/holiday, roll forward to next biz day.
        A make-up working weekend (CN 调休) is a business day.
      - Same calendar_version → same answer; bumping version requires explicit re-confirmation.
    """
    if jurisdiction not in RULES:
        # Stub for unsupported jurisdictions
        return {
            "received_date": received_date.isoformat(),
            "statutory_deadline": (received_date + timedelta(days=60)).isoformat(),
            "recommended_internal_deadline": (received_date + timedelta(days=53)).isoformat(),
            "days_remaining": 60,
            "holiday_calendar_version": calendar_version or AUTO_CALENDAR,
            "warnings": [f"Jurisdiction {jurisdiction} not yet implemented; using 60-day default."],
            "rules_reviewed": RULES_REVIEWED,
        }

    rule = RULES[jurisdiction]
    case_tz = ZoneInfo(rule.timezone_name)
    # Load from the versioned, client-updatable calendar (cached). Falls back to
    # the hard-coded mirror; resolves to empty + a loud warning if the requested
    # version has no source at all (never a silently-wrong date).
    # Convert received date to case timezone, take the date part
    received_local = received_date.astimezone(case_tz)
    assumptions: list[str] = []
    stated_months = None
    if oa_sequence is None and rule.subsequent_response_months:
        # Precedence: explicit oa_sequence > period printed on the notice >
        # 第N次 detected in the text > unknown (earlier period + note).
        stated_months = detect_cn_stated_months(oa_text)
        if stated_months is None:
            oa_sequence = detect_cn_oa_sequence(oa_text)
    if service_date is None and rule.start_event == "service":
        service_date = extract_service_date(oa_text)
    if service_date is not None and service_date < received_local.date():
        assumptions.append(
            f"Service date {service_date} is before the mailing date "
            f"{received_local.date()} — ignored; check the dates."
        )
        service_date = None
    start_date, start_basis, start_notes = select_start_date(
        jurisdiction, received_local.date(), service_date=service_date
    )
    months, days, period_label, period_notes = select_period(
        jurisdiction,
        applicant_domestic=applicant_domestic,
        oa_sequence=oa_sequence,
        stated_months=stated_months,
    )
    assumptions += start_notes + period_notes
    if months:
        raw_deadline_date = add_calendar_months(start_date, months)
    else:
        raw_deadline_date = start_date + timedelta(days=days)
    # "auto" picks each needed year's calendar; +1 year so a roll-forward
    # across New Year still sees next year's holidays.
    years = range(received_local.year, raw_deadline_date.year + 2)
    requested_version = calendar_version
    holidays, calendar_version, calendar_missing = resolve_calendar(
        jurisdiction, requested_version, years
    )
    workdays = resolve_workdays(jurisdiction, requested_version, years)

    # Roll forward if last day is weekend/holiday (a 调休 working weekend is not)
    final_deadline_date = _next_business_day(raw_deadline_date, holidays, workdays)
    rolled = final_deadline_date != raw_deadline_date

    # Year-boundary guard. The loaded calendar version is keyed to a year
    # (e.g. "2025.1" covers 2025). When the statutory deadline lands in — OR
    # ROLLS INTO — a year the calendar doesn't cover, the roll-forward can't see
    # that year's holidays (it could land on, say, 2026 元旦 and not know it).
    # We check BOTH the raw deadline year and the final (post-roll) year against
    # the loaded calendar: if EITHER falls in a year with no holidays loaded, we
    # surface a loud warning rather than silently computing against a partial
    # calendar. (Checking only the raw year missed the case where the roll
    # itself crosses the boundary — e.g. JP 12/31 rolling onto 1/1.)
    loaded_years = {h.year for h in holidays}
    deadline_year_covered = (
        raw_deadline_date.year in loaded_years and final_deadline_date.year in loaded_years
    )

    # Recommended internal deadline = ~7 days earlier. Roll BACKWARD to the
    # previous business day — rolling forward (the old behaviour) could land
    # the "earlier" internal warning ON or AFTER the statutory date whenever
    # those 7 days span a long weekend/holiday block. Then hard-guarantee it
    # is strictly before the statutory deadline.
    recommended_raw = final_deadline_date - timedelta(days=7)
    recommended = _prev_business_day(recommended_raw, holidays, workdays)
    while recommended >= final_deadline_date:
        recommended = _prev_business_day(recommended - timedelta(days=1), holidays, workdays)

    # Express deadlines as 23:59 case-local time
    statutory_dt = datetime.combine(final_deadline_date, time(23, 59), tzinfo=case_tz)
    recommended_dt = datetime.combine(recommended, time(23, 59), tzinfo=case_tz)

    days_remaining = (final_deadline_date - datetime.now(case_tz).date()).days

    warnings = []
    if calendar_missing:
        warnings.append(
            f"⛔ Holiday calendar {jurisdiction}_{calendar_version} could not be "
            f"loaded (no JSON file, no fallback). Computed against an EMPTY "
            f"holiday set — VERIFY this deadline manually; it may be wrong."
        )
    elif not deadline_year_covered:
        # Deadline lands in / rolled into a year the loaded calendar doesn't
        # cover. Name the uncovered year(s) explicitly.
        uncovered = sorted({raw_deadline_date.year, final_deadline_date.year} - loaded_years)
        years_str = ", ".join(str(y) for y in uncovered)
        warnings.append(
            f"⚠️  Statutory deadline involves year(s) {years_str}, but the loaded "
            f"calendar {jurisdiction}_{calendar_version} does not cover them. "
            f"Those years' holidays were NOT considered — load the matching "
            f"calendar(s) and recompute."
        )
    if rolled:
        warnings.append(
            f"Statutory deadline rolled from {raw_deadline_date} (weekend/holiday) "
            f"to {final_deadline_date}."
        )
    if days_remaining < 14:
        warnings.append(f"⚠️  Only {days_remaining} days remaining — escalate immediately.")
    if days_remaining < 0:
        warnings.append(f"⛔ DEADLINE PASSED {abs(days_remaining)} days ago.")
    # Assumptions (unknown domicile / OA sequence / service date) also go into
    # the human-readable warnings so every existing consumer shows them.
    warnings.extend(f"ℹ️  {a}" for a in assumptions)

    # NOTE: the returned dict's keys are constrained to the wire model
    # (backend.shared.models.DeadlineInfo, which forbids extras). The structured
    # flags (calendar_missing / deadline_year_covered) are surfaced via the
    # human-readable `warnings` list above, and are also queryable out-of-band
    # via calendar_is_missing() / deadline_year_is_covered() for callers/tests
    # that need to branch without string-matching.
    return {
        "received_date": received_local.isoformat(),
        "statutory_deadline": statutory_dt.isoformat(),
        "recommended_internal_deadline": recommended_dt.isoformat(),
        "days_remaining": days_remaining,
        "holiday_calendar_version": calendar_version,
        "warnings": warnings,
        # Q19 transparency: which date the period actually ran from.
        "mailing_date": received_local.date().isoformat(),
        "start_date": start_date.isoformat(),
        "start_date_basis": start_basis,
        "period_applied": period_label,
        "assumptions": assumptions,
        "rules_reviewed": RULES_REVIEWED,  # Q21
    }


# ---------- Self-tests (run with: python -m backend.ai_engine.deadline) ----------


def _self_test():
    """Run common edge cases.  Production replaces with pytest."""
    # Case 1: TW received 2025-01-15 → 2 months → 2025-03-15 (Sat) → roll to 2025-03-17
    r = calculate_deadline(datetime(2025, 1, 15, 9, 0, tzinfo=UTC), "TW", "2025.1")
    assert r["statutory_deadline"].startswith("2025-03-17"), r["statutory_deadline"]

    # Case 2: TW received 2024-12-01 → 60 days → 2025-01-30 → 春節 → roll to next biz day
    r = calculate_deadline(datetime(2024, 12, 1, 9, 0, tzinfo=UTC), "TW", "2025.1")
    assert "2025-02" in r["statutory_deadline"], r["statutory_deadline"]

    # Case 3: US received 2025-04-01 → 3 calendar months → 2025-07-01 (Tue) → keep
    r = calculate_deadline(datetime(2025, 4, 1, 9, 0, tzinfo=UTC), "US", "2025.1")
    assert r["statutory_deadline"].startswith("2025-07-01"), r["statutory_deadline"]

    # Case 4: jurisdiction stub (still works for anything not in RULES)
    r = calculate_deadline(datetime(2025, 4, 1, 9, 0, tzinfo=UTC), "DE", "2025.1")
    assert any("not yet implemented" in w for w in r["warnings"])

    # Case 5: CN — +120 days lands on the 国庆 golden week; must roll past it
    # and land on a business day, in +08:00 (Asia/Shanghai).
    r = calculate_deadline(datetime(2025, 6, 9, 9, 0, tzinfo=UTC), "CN", "2025.1")
    assert r["statutory_deadline"].endswith("+08:00"), r["statutory_deadline"]
    cn_sd = date.fromisoformat(r["statutory_deadline"][:10])
    assert cn_sd.weekday() < 5 and cn_sd not in get_holidays("CN", "2025.1"), cn_sd

    # Case 6: KR — +60 days, Asia/Seoul (+09:00), rolls off weekends/holidays.
    r = calculate_deadline(datetime(2025, 8, 1, 9, 0, tzinfo=UTC), "KR", "2025.1")
    assert r["statutory_deadline"].endswith("+09:00"), r["statutory_deadline"]
    kr_sd = date.fromisoformat(r["statutory_deadline"][:10])
    assert kr_sd.weekday() < 5 and kr_sd not in get_holidays("KR", "2025.1"), kr_sd

    # Case 7: EP — +120 days, Europe/Munich; business day.
    r = calculate_deadline(datetime(2025, 4, 1, 9, 0, tzinfo=UTC), "EP", "2025.1")
    ep_sd = date.fromisoformat(r["statutory_deadline"][:10])
    assert ep_sd.weekday() < 5 and ep_sd not in get_holidays("EP", "2025.1"), ep_sd

    print("✓ deadline self-test passed")


if __name__ == "__main__":
    _self_test()
