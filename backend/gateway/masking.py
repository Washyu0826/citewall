"""Data masking layer (Q10).

Strategy: PII + customer identifiers, regex + dictionary based.

Key invariants (per Q3 hybrid):
    - The mapping table NEVER leaves on-prem.
    - Outbound LLM payload only sees placeholders.
    - Response un-masking happens server-side before showing the attorney.

At-rest confidentiality of the un-redaction table (Q3/Q10 — "crown jewel"):
    - The `original` column is the reversible map back to real PII / client
      identifiers. It is ENCRYPTED AT REST with authenticated encryption
      (Fernet / AES-128-CBC + HMAC-SHA256). The on-disk SQLite file holds only
      ciphertext, so copying `redaction_mapping.db` alone is NOT enough to
      un-redact anything.
    - Encryption keys are PER-TENANT: each tenant's subkey is derived from a
      single master key (`settings.MAPPING_ENCRYPTION_KEY`) via HKDF-SHA256 with
      the tenant_id as the info parameter. A leaked tenant_a table therefore
      cannot be decrypted with tenant_b's key.
    - The master key lives OUTSIDE the database (env / secret manager), so DB
      theft alone is insufficient — you also need the master key. For the POC a
      deterministic dev key is derived when the env var is unset (a WARNING is
      logged; a real key MUST be configured in production).

Per-tenant uploadable dictionaries (Q10 layer 2):
    - A firm's customer-identifier rules (case numbers, client codes, project
      codenames) live in ``data/tenant_dicts/<tenant_id>.json`` and are loaded +
      compiled + cached at runtime, so white-glove onboarding a new client's
      patterns is a file drop + ``reload_tenant_dictionary(tenant_id)`` — NOT a
      code change + gateway restart. The hard-coded ``TENANT_DICTIONARIES``
      below remains a fallback when no JSON file exists for a tenant.

A real implementation would also:
    - Run an NER model for free-text customer references
    - Hash PII with HMAC-tenant-key so the same email → same placeholder
      (lets LLM reason about co-occurrence without knowing identity)
"""

from __future__ import annotations

import base64
import bisect
import hashlib
import hmac
import json
import logging
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from re import Pattern

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.shared.config import MAPPING_DB_PATH, TENANT_DICTS_DIR, settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaskRule:
    rule_id: str
    pattern: Pattern[str]
    placeholder_prefix: str
    description: str


# ---------------------------------------------------------------------------
# Unicode pre-normalisation: zero-width strip + homoglyph/confusable folding
# (Agent A — Day 12A hardening of the M-6 Unicode-bypass defence)
# ---------------------------------------------------------------------------
#
# The threat model: an attacker (or a sloppy Word export) interleaves invisible
# code points or substitutes look-alike characters into PII so the ASCII-anchored
# regex inventory in PII_RULES never matches. Two distinct evasion classes:
#
#   1. ZERO-WIDTH / invisible code points splitting a token, e.g.
#        ``09<U+200B>12-345-678``  → phone_tw never matches the broken digit run.
#      NFKC does NOT remove these (U+200B is not a compatibility decomposition),
#      so they MUST be stripped in a separate pre-pass BEFORE NFKC.
#
#   2. HOMOGLYPH / confusable substitution, e.g.
#        ``jоhn@apex-ip.com`` where ``о`` is Cyrillic U+043E, not Latin ``o`` →
#      the email local-part class ``[a-zA-Z0-9._%+-]`` rejects the Cyrillic
#      letter and the address is only partially (or not) redacted. NFKC does NOT
#      fold cross-script confusables (they are distinct characters, not
#      compatibility variants), so we apply an explicit confusables map.
#
# Ordering is load-bearing:  strip_zero_width → fold_confusables → NFKC.
# (Confusable folding before NFKC so the folded ASCII then survives NFKC; NFKC
#  last so fullwidth/ligature compatibility variants still collapse.)

# Invisible / zero-width / bidi-control code points to delete outright. NFKC
# does NOT remove these, so this is a mandatory separate pre-pass:
#   U+00AD SOFT HYPHEN            U+180E MONGOLIAN VOWEL SEPARATOR
#   U+200B ZERO WIDTH SPACE       U+200C ZERO WIDTH NON-JOINER
#   U+200D ZERO WIDTH JOINER      U+200E/200F LEFT/RIGHT-TO-LEFT MARK
#   U+202A-202E bidi embed/override   U+2060 WORD JOINER
#   U+2061-2064 invisible math ops    U+FEFF ZWNBSP / BOM
_ZERO_WIDTH_RE = re.compile(
    "["
    "\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f"
    "\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f"
    "\ufeff\uffa0\U000e0000-\U000e007f"
    "]"
)  # soft hyphen, CGJ, ALM, Hangul fillers, Mongolian FVS/MVS, ZW*/LRM/RLM,
#    bidi embeddings+isolates (U+2066-2069), word joiner..nominal digit
#    shapes, variation selectors, BOM, tag characters (U+E0000-E007F)


def strip_zero_width(text: str) -> str:
    """Delete zero-width / invisible / bidi-control code points.

    Run BEFORE NFKC and confusable folding so a PII token split by invisible
    characters (``09<U+200B>12...``) is rejoined into a matchable run. NFKC does
    not remove these, so this is a mandatory separate pre-pass.
    """
    return _ZERO_WIDTH_RE.sub("", text)


# Homoglyph / confusables fold map. Deliberately SCOPED to characters that
# confuse the ASCII alphabet + digits the PII rules rely on (Latin a-z / A-Z /
# 0-9 and the email punctuation ``@ . -``). We do NOT attempt a full Unicode
# confusables table — that risks corrupting legitimate CJK / accented prose. The
# entries are the high-frequency Cyrillic + Greek look-alikes plus a few
# confusable punctuation marks. Folding maps to the canonical ASCII so the
# existing regexes fire and the placeholder maps back to ASCII (consistent with
# the already-documented NFKC lossy round-trip).
_CONFUSABLE_MAP: dict[str, str] = {
    # --- Cyrillic capitals that look like Latin capitals ---
    "А": "A",
    "В": "B",
    "С": "C",
    "Е": "E",
    "Н": "H",
    "К": "K",
    "М": "M",
    "О": "O",
    "Р": "P",
    "Т": "T",
    "Х": "X",
    "І": "I",
    "Ј": "J",
    "Ѕ": "S",
    "Ї": "I",
    "Ү": "Y",
    # --- Cyrillic smalls that look like Latin smalls ---
    "а": "a",
    "в": "v",
    "с": "c",
    "е": "e",
    "н": "h",
    "к": "k",
    "м": "m",
    "о": "o",
    "р": "p",
    "т": "t",
    "х": "x",
    "і": "i",
    "ј": "j",
    "ѕ": "s",
    "у": "y",
    # --- Greek capitals that look like Latin capitals ---
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
    # --- Greek smalls that look like Latin smalls ---
    "α": "a",
    "ο": "o",
    "ρ": "p",
    "υ": "u",
    "ν": "v",
    "χ": "x",
    # --- Confusable punctuation used in emails / IDs ---
    "＠": "@",
    "﹫": "@",
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "－": "-",
    "․": ".",
    "．": ".",
}

# Single translation table compiled once (str.translate is C-fast).
_CONFUSABLE_TABLE = {ord(k): v for k, v in _CONFUSABLE_MAP.items()}


def fold_confusables(text: str) -> str:
    """Fold a scoped set of homoglyph / confusable code points to their ASCII
    look-alikes so PII hidden behind cross-script substitution is detectable.

    Scoped on purpose (see ``_CONFUSABLE_MAP``): only characters that imitate
    the ASCII alphabet/digits/email-punctuation the PII rules depend on. CJK and
    legitimate accented characters are untouched.
    """
    return text.translate(_CONFUSABLE_TABLE)


def normalize_for_detection(text: str) -> str:
    """Canonicalise inbound text for PII detection.

    Pipeline (order matters):
      1. ``strip_zero_width`` — delete invisible separators that split tokens.
      2. ``fold_confusables`` — map homoglyphs to ASCII look-alikes.
      3. NFKC — collapse fullwidth / ligature / compatibility variants.

    The result is the canonical form the regexes run against AND the form stored
    as the mapping ``original`` (so ``unmask`` returns this canonical spelling —
    the already-documented NFKC lossy round-trip, now also lossy w.r.t. stripped
    invisibles and folded homoglyphs, which is the intended hardening).
    """
    text = strip_zero_width(text)
    text = fold_confusables(text)
    return unicodedata.normalize("NFKC", text)


# --- Built-in PII rules (Q10 layer 1) ---
#
# Regex design notes (Agent A — Day 12A coverage expansion):
#   * Patterns run AFTER ``normalize_for_detection`` (zero-width stripped,
#     homoglyphs folded, NFKC), so they only need to match canonical ASCII.
#   * Every rule is tuned to AVOID over-redacting ordinary patent prose:
#     patent numbers (``US10876543``, ``TW201912345``), claim refs (``Claim 1``),
#     figure refs (``FIG. 3``), and statute cites (``35 U.S.C. § 103``) must
#     pass through untouched — they are not PII and the AI Engine needs them.
#   * The egress guard (orchestrator._scan_value_for_pii) REUSES PII_RULES, so a
#     rule that over-matches would also wrongly BLOCK legitimate outbound
#     payloads. Precision here is a hard requirement, not a nicety.

PII_RULES: list[MaskRule] = [
    MaskRule(
        rule_id="email",
        # Linear (FAILURE_LOG B-53, B-54). Unbounded, every start inside a long
        # run of local-part characters scanned to the end of the run for "@"
        # (~10 s at 96k). Two alternatives instead:
        #  1. the whole run, from its first character (possessive: "@" is not in
        #     the class, so giving characters back can never find another "@");
        #  2. up to 256 characters from anywhere — for an address glued to the
        #     end of the previous match ("a@b.com1x@y.com"), which (1) cannot
        #     see because its first character follows a local-part character.
        # The one difference from the old rule: in that glued case, a local part
        # longer than 256 (RFC 5321 allows 64) keeps its leading characters
        # unmasked. Existence (the egress guard's search) is unchanged.
        pattern=re.compile(
            r"(?:(?<![a-zA-Z0-9._%+-])[a-zA-Z0-9._%+-]++|[a-zA-Z0-9._%+-]{1,256})"
            r"@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        ),
        placeholder_prefix="EMAIL",
        description="email address",
    ),
    MaskRule(
        rule_id="phone_tw",
        pattern=re.compile(r"\b09\d{2}[-\s]?\d{3}[-\s]?\d{3}\b"),
        placeholder_prefix="PHONE",
        description="Taiwan mobile phone",
    ),
    MaskRule(
        # Taiwan landline: area code in parens or with a separator, then 7-8
        # digits. Anchored on the leading ``(0X)`` / ``0X-`` shape so it does
        # NOT swallow bare 8-digit patent-ish numbers. Examples it must catch:
        #   (02)27000001   (02)2700-0001   02-2700-0001   (07)123-4567
        rule_id="phone_tw_landline",
        pattern=re.compile(
            r"\(0\d{1,2}\)\s?\d{3,4}[-\s]?\d{4}\b"
            r"|\b0\d{1,2}-\d{3,4}-\d{4}\b"
        ),
        placeholder_prefix="PHONE",
        description="Taiwan landline (area code + number)",
    ),
    MaskRule(
        rule_id="phone_us",
        pattern=re.compile(r"\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        placeholder_prefix="PHONE",
        description="US phone (loose)",
    ),
    MaskRule(
        # International phone in E.164-ish form: a leading ``+`` then 8-15 digits
        # with optional separators. Anchored on the ``+`` so it never collides
        # with patent numbers (which have no leading ``+``).
        rule_id="phone_intl",
        pattern=re.compile(r"(?<!\w)\+\d[\d\-\s().]{7,16}\d\b"),
        placeholder_prefix="PHONE",
        description="international phone (E.164-ish, +-anchored)",
    ),
    MaskRule(
        rule_id="tw_id",
        pattern=re.compile(r"\b[A-Z][12]\d{8}\b"),
        placeholder_prefix="TW_ID",
        description="Taiwan national ID",
    ),
    MaskRule(
        # ROC 統一編號 (business/company tax ID): exactly 8 digits. To avoid
        # over-redacting arbitrary 8-digit runs (which appear in patent
        # numbers, dates, etc.) we REQUIRE an explicit contextual marker
        # immediately preceding. A bare ``27000001`` is NOT redacted, but
        # ``統一編號：27000001`` is. match.group(0) (incl. the marker) is masked.
        rule_id="tw_company_tax_id",
        pattern=re.compile(
            # \s*+ (possessive): two \s* around the optional marker split a run
            # of whitespace every possible way — O(n²) after a label (B-54).
            # Nothing that follows any of them can match whitespace.
            r"(?:統一編號|統編|營利事業(?:統一)?編號|公司統編|Tax\s*+ID|Uniform\s*+(?:Business\s*+)?No\.?)"
            r"\s*+[:：#＃]?\s*+\d{8}\b",
            re.IGNORECASE,
        ),
        placeholder_prefix="TW_TAX_ID",
        description="ROC company uniform (tax) ID, context-anchored",
    ),
    MaskRule(
        # Passport number: contextual marker + 7-9 digits (optionally 1-2
        # leading letters). Context-anchored to avoid catching patent /
        # publication numbers.
        rule_id="passport",
        pattern=re.compile(
            # \s*+ (possessive), as in tw_company_tax_id (B-54).
            r"(?:護照(?:號碼|號)?|Passport(?:\s*+(?:No|Number))?\.?)"
            r"\s*+[:：#＃]?\s*+[A-Z]{0,2}\d{7,9}\b",
            re.IGNORECASE,
        ),
        placeholder_prefix="PASSPORT",
        description="passport number, context-anchored",
    ),
    MaskRule(
        rule_id="ssn",
        pattern=re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        placeholder_prefix="SSN",
        description="US SSN",
    ),
    MaskRule(
        # IPv4 address with strict 0-255 octets. Patent numbers are not
        # dotted-quads, so no collision with patent prose.
        rule_id="ipv4",
        pattern=re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
        ),
        placeholder_prefix="IP",
        description="IPv4 address",
    ),
    MaskRule(
        # IPv6 address (full or compressed). Requires >=2 colon-separated hex
        # groups so it can't match ordinary prose.
        rule_id="ipv6",
        pattern=re.compile(
            r"\b(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}\b"
            r"|\b(?:[0-9A-Fa-f]{1,4}:){1,7}:(?!\d)"
        ),
        placeholder_prefix="IP",
        description="IPv6 address",
    ),
]

# --- Customer identifier rules (Q10 layer 2) ---
# Each tenant provides its own.  POC ships demo dictionaries.

TENANT_DICTIONARIES: dict[str, list[MaskRule]] = {
    "tenant_a": [
        MaskRule(
            rule_id="apex_case_no",
            pattern=re.compile(r"\bAPEX-\d{4}-\d{3,5}\b"),
            placeholder_prefix="CASE_REF",
            description="Apex internal case number",
        ),
        MaskRule(
            rule_id="apex_client_code",
            pattern=re.compile(r"\bCL-[A-Z]{2,4}\d{2,4}\b"),
            placeholder_prefix="CLIENT_CODE",
            description="Apex client code",
        ),
    ],
    "tenant_b": [
        MaskRule(
            rule_id="beta_proj_code",
            pattern=re.compile(r"\bBL-PRJ-\d{4}\b"),
            placeholder_prefix="PROJ",
            description="BetaLegal project code",
        ),
    ],
}


# --- Per-tenant UPLOADABLE dictionary loader (Q10 — kill the hard-coded one) -
#
# The hard-coded ``TENANT_DICTIONARIES`` above used to be the ONLY source of a
# firm's customer-identifier rules, so onboarding a new client's case-number /
# client-code patterns meant a Python edit + gateway restart. The real product
# needs white-glove onboarding: an ops engineer drops a tenant's JSON dictionary
# at ``data/tenant_dicts/<tenant_id>.json`` and reloads — no deploy.
#
# Resolution order for a tenant's layer-2 rules:
#   1. ``data/tenant_dicts/<tenant_id>.json``  (uploaded — authoritative)
#   2. ``TENANT_DICTIONARIES[tenant_id]``      (hard-coded fallback — nothing
#      breaks if the data dir is absent / the file was never shipped)
#   3. ``[]``                                  (unknown tenant → built-ins only)
#
# The built-in ``PII_RULES`` are ALWAYS prepended regardless (layer 1), so the
# merge order is exactly as before: ``PII_RULES + <tenant layer-2 rules>``.
#
# JSON schema (one object per rule under a top-level ``rules`` array):
#   {"rule_id": str, "pattern": str (regex),
#    "placeholder_prefix": str, "description": str}

# Safety guard against catastrophic-backtracking / DoS regexes uploaded by a
# tenant. Python's ``re`` is backtracking (no linear-time guarantee), so a
# pattern like ``(a+)+$`` against adversarial input can hang the masker — and
# the masker runs on the hot path of EVERY redact() call. For the POC we apply
# a simple, documented LENGTH CAP: a pattern longer than this is rejected at
# load time (skipped + logged), on the heuristic that pathological ReDoS
# patterns and legitimate identifier patterns differ wildly in length (real
# case/client-code regexes are short, ~10-40 chars). This is NOT a true ReDoS
# detector — a short evil pattern can still slip through. Production should add
# a real timeout-bounded matcher (e.g. the `regex` module's `timeout=`, or run
# matching in a watchdog thread) and/or a linter that flags nested quantifiers.
MAX_TENANT_PATTERN_LEN = 200

# Module-level cache of compiled per-tenant dictionaries, keyed by tenant_id.
# We cache because redact() is hot and re-reading + recompiling a tenant's JSON
# on every call would be wasteful. ``reload_tenant_dictionary`` invalidates a
# single tenant; ``_loaded_dicts.clear()`` (or that helper with no arg) clears
# all. A sentinel distinguishes "loaded, empty" from "not yet loaded".
_loaded_dicts: dict[str, list[MaskRule]] = {}
_loaded_dicts_lock = threading.Lock()


def _tenant_dict_path(tenant_id: str) -> Path:
    return TENANT_DICTS_DIR / f"{tenant_id}.json"


def _compile_tenant_rules(tenant_id: str, raw_rules: list) -> list[MaskRule]:
    """Compile a tenant's raw JSON rule list into ``MaskRule`` objects.

    DEFENSIVE: a single malformed / dangerous / regex-invalid rule MUST NOT
    abort loading the rest of the tenant's dictionary, and MUST NOT crash
    redaction for everyone. Each rule is validated independently; failures are
    logged at WARNING and the rule is skipped.
    """
    compiled: list[MaskRule] = []
    seen_ids: set[str] = set()
    for entry in raw_rules:
        if not isinstance(entry, dict):
            logger.warning(
                "tenant=%s: skipping malformed dictionary entry (not an object): %r",
                tenant_id,
                entry,
            )
            continue
        rule_id = entry.get("rule_id")
        pattern_str = entry.get("pattern")
        placeholder_prefix = entry.get("placeholder_prefix")
        description = entry.get("description", "")

        if not rule_id or not pattern_str or not placeholder_prefix:
            logger.warning(
                "tenant=%s: skipping dictionary rule missing rule_id/pattern/"
                "placeholder_prefix: %r",
                tenant_id,
                entry,
            )
            continue
        if rule_id in seen_ids:
            logger.warning(
                "tenant=%s: duplicate rule_id %r in dictionary; skipping later copy",
                tenant_id,
                rule_id,
            )
            continue
        # DoS guard: reject over-long patterns (see MAX_TENANT_PATTERN_LEN note).
        if len(pattern_str) > MAX_TENANT_PATTERN_LEN:
            logger.warning(
                "tenant=%s: skipping rule %r — pattern length %d exceeds the "
                "%d-char safety cap (possible catastrophic-backtracking risk)",
                tenant_id,
                rule_id,
                len(pattern_str),
                MAX_TENANT_PATTERN_LEN,
            )
            continue
        # Compile defensively: a bad regex from one tenant must never break
        # redaction for the other rules / other tenants.
        try:
            pattern = re.compile(pattern_str)
        except re.error as exc:
            logger.warning(
                "tenant=%s: skipping rule %r — invalid regex %r: %s",
                tenant_id,
                rule_id,
                pattern_str,
                exc,
            )
            continue

        compiled.append(
            MaskRule(
                rule_id=str(rule_id),
                pattern=pattern,
                placeholder_prefix=str(placeholder_prefix),
                description=str(description),
            )
        )
        seen_ids.add(rule_id)
    return compiled


def _read_tenant_dictionary(tenant_id: str) -> list[MaskRule]:
    """Read + compile a tenant's dictionary from disk, with hard-coded fallback.

    Returns the tenant's layer-2 ``MaskRule`` list (NOT including PII_RULES).
    Never raises: any IO/JSON failure degrades to the hard-coded
    ``TENANT_DICTIONARIES`` entry (or ``[]`` for an unknown tenant).
    """
    path = _tenant_dict_path(tenant_id)
    if not path.exists():
        # No uploaded dict → fall back to the hard-coded demo rules so nothing
        # breaks when the data dir is absent (e.g. a fresh checkout / CI).
        return list(TENANT_DICTIONARIES.get(tenant_id, []))

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(
            "tenant=%s: failed to read/parse dictionary %s (%s); falling back "
            "to hard-coded TENANT_DICTIONARIES.",
            tenant_id,
            path,
            exc,
        )
        return list(TENANT_DICTIONARIES.get(tenant_id, []))

    raw_rules = doc.get("rules", []) if isinstance(doc, dict) else []
    if not isinstance(raw_rules, list):
        logger.warning(
            "tenant=%s: dictionary %s has a non-list 'rules'; ignoring file, "
            "falling back to hard-coded TENANT_DICTIONARIES.",
            tenant_id,
            path,
        )
        return list(TENANT_DICTIONARIES.get(tenant_id, []))

    return _compile_tenant_rules(tenant_id, raw_rules)


def get_tenant_rules(tenant_id: str) -> list[MaskRule]:
    """Return a tenant's compiled layer-2 rules, loading + caching on first use.

    Thread-safe. The compiled list is cached per tenant_id; call
    ``reload_tenant_dictionary(tenant_id)`` after an upload to pick up changes.
    """
    cached = _loaded_dicts.get(tenant_id)
    if cached is not None:
        return cached
    with _loaded_dicts_lock:
        # Re-check inside the lock (another thread may have populated it).
        cached = _loaded_dicts.get(tenant_id)
        if cached is not None:
            return cached
        rules = _read_tenant_dictionary(tenant_id)
        _loaded_dicts[tenant_id] = rules
        return rules


def reload_tenant_dictionary(tenant_id: str | None = None) -> list[MaskRule]:
    """White-glove "we just uploaded your dict" hook: drop the cache so the next
    redact() re-reads from disk.

    With a ``tenant_id`` → invalidate + eagerly reload that one tenant, returning
    its freshly compiled rules. With ``None`` → invalidate ALL tenants (lazy
    reload on next access) and return an empty list.
    """
    with _loaded_dicts_lock:
        if tenant_id is None:
            _loaded_dicts.clear()
            return []
        _loaded_dicts.pop(tenant_id, None)
        rules = _read_tenant_dictionary(tenant_id)
        _loaded_dicts[tenant_id] = rules
        return rules


# --- Named-entity masking: person / organisation / address (Q25) -------------
#
# The regex PII table above only covers machine-shaped identifiers (email,
# phone, IDs). Free-text identity — who the inventors are, which company is the
# applicant, where the firm sits — sailed through to the LLM. This layer adds
# it, behind ``settings.NER_BACKEND``:
#
#   none  — disabled.
#   rules — deterministic, dependency-free patterns tuned for PRECISION on OA /
#           patent text. Technical prose must survive untouched (claims, element
#           names like 充電站 / 電路, chemical terms), so every rule is anchored:
#             * PERSON  — only a name right after a role label
#                         (發明人：/聯絡人：/審查委員：/Inventor:/Examiner: …)
#             * ORG     — legal-form suffix required (股份有限公司 / 事務所 /
#                         Inc. / Co., Ltd. / LLC / Law Firm …); a bare 公司 is
#                         NOT enough (電力公司 is technical context)
#             * ADDRESS — a TW street address needs 路/街 + 號 AND an
#                         administrative/segment marker (市/縣/區/段/巷/弄),
#                         never preceded by 電/迴/線… (so 電路…號 is safe); a
#                         US address needs number + Capitalised name + suffix;
#                         or anything after an explicit 地址：/Address: label.
#   ckip  — ckip-transformers zh-TW NER (PERSON / ORG) UNIONED with `rules`.
#           Lazy import; any failure (not installed, model download blocked)
#           logs once and falls back to `rules`.
#
# NER runs AFTER normalisation and AFTER the regex/tenant rules, on the text
# that already carries their placeholders; spans overlapping an existing
# placeholder are skipped, so redact() stays idempotent. It is deliberately NOT
# part of PII_RULES: the egress guard reuses PII_RULES, and a free-text entity
# heuristic must never be able to block an outbound payload.

_CJK = "一-鿿"
_PLACEHOLDER_TOKEN_RE = re.compile(r"\[[A-Z_]+_[0-9A-F]{8}\]")

# rule_id per placeholder prefix (surfaced in `triggered` / audit masked rules).
_NER_RULE_IDS = {"PERSON": "ner_person", "ORG": "ner_org", "ADDRESS": "ner_address"}
# Overlap resolution: higher wins (an ORG after 申請人： beats the PERSON reading).
_NER_PRIORITY = {"ORG": 3, "ADDRESS": 2, "PERSON": 1}

# ---- ORG ----
_TW_ORG_SUFFIX = (
    "(?:股份有限公司|有限責任公司|有限公司|"
    "專利商標事務所|商標專利事務所|專利事務所|法律事務所|律師事務所|會計師事務所|事務所)"
)
_TW_ORG_RE = re.compile(rf"[{_CJK}A-Za-z0-9&·]{{2,24}}?{_TW_ORG_SUFFIX}")
# Leading words a greedy CJK run can swallow before the real name
# ("申請人昕澄科技股份有限公司", "委任本事務所").
_TW_ORG_LEAD_WORDS = (
    "受文者",
    "專利權人",
    "申請人",
    "發明人",
    "代理人",
    "委任",
    "委託",
    "本案",
    "由",
    "係",
    "為",
    "之",
    "與",
    "及",
    "和",
    "的",
    "將",
    "於",
    "經",
    "本",
    "貴",
    "該",
    "其",
)
# Linear (B-54, B-55). Unbounded, on "A.A.A.…" every word boundary started a
# scan to the end of the run — O(n²), ~24 s at 96k. Two branches, as in the
# e-mail rule: a word from the first character of its run, whole (possessive:
# space and tab are not in the class, so it ends where the run ends anyway);
# or, from inside a run, at most 256 characters — for a name that starts after
# "x.", "e-" or right after the previous match ("…Inc.Bar Corp"). The first
# fix (64 for every word) left long words unmasked (B-55). Words 2..6 follow
# whitespace, so they always take the first branch.
_EN_ORG_RE = re.compile(
    r"\b(?:(?:(?<![A-Za-z0-9&'.\-])[A-Z][A-Za-z0-9&'.\-]*+|[A-Z][A-Za-z0-9&'.\-]{0,255})[ \t]+){1,6}"
    r"(?:Inc\.|Inc\b|Incorporated\b|Corp\.|Corp\b|Corporation\b|Co\.,?[ \t]*Ltd\.?|"
    r"Ltd\.|Ltd\b|LLC\b|L\.L\.C\.|LLP\b|L\.L\.P\.|PLLC\b|GmbH\b|AG\b|S\.A\.|K\.K\.|"
    r"B\.V\.|PLC\b|Law[ \t]+Firm\b|Law[ \t]+Group\b|Law[ \t]+Offices?\b)"
)
_EN_LEAD_WORDS = {
    "The",
    "See",
    "By",
    "In",
    "Of",
    "And",
    "From",
    "To",
    "With",
    "Per",
    "For",
    "Applicant",
    "Assignee",
    "Owner",
}

# ---- ADDRESS ----
# Linear time (FAILURE_LOG B-53). Adjacent `\s*` around optional groups let a
# run of whitespace be split in every possible way: 3,000 spaces took ~50 s,
# and a request near the size cap would never finish. `\s*+` is possessive
# (nothing after any of them can match whitespace, so giving spaces back can
# never help), and a match may start inside a whitespace run only at the
# run's first character — the leftmost match the old pattern returned
# anyway — so positions inside a run are rejected in O(1). Same matches.
_TW_ADDR_RE = re.compile(
    r"(?:(?<!\s)|(?=\S))"
    rf"(?:[{_CJK}]{{1,4}}[縣市])?\s*+(?:[{_CJK}]{{1,4}}[區鄉鎮市])?\s*+"
    rf"[{_CJK}0-9]{{1,8}}?(?<![電迴線通網支旁光管水油氣鐵道])(?:路|街|大道)\s*+"
    r"(?:[一二三四五六七八九十0-9]++\s*+段)?\s*+(?:[0-9]++\s*+巷)?\s*+(?:[0-9]++\s*+弄)?\s*+"
    r"[0-9]++(?:\s*+之\s*+[0-9]++)?\s*+號(?:\s*+[0-9]++\s*+樓(?:\s*+之\s*+[0-9]++)?)?"
)
_TW_ADDR_MARKERS = re.compile("[縣市區鄉鎮段巷弄]")
_TW_ADDR_LEAD = re.compile("^(?:設於|位於|座落於|坐落於|在|於|至|往)")
_EN_ADDR_RE = re.compile(
    r"\b\d{1,6}[ \t]+(?:[A-Z][a-z]+\.?[ \t]+){1,4}"
    r"(?:Street|St\.|Avenue|Ave\.|Road|Rd\.|Boulevard|Blvd\.|Drive|Dr\.|Lane|Ln\.|"
    r"Way|Court|Ct\.|Place|Pl\.|Parkway|Pkwy\.)"
    r"(?:,?[ \t]*(?:Suite|Ste\.|Apt\.|Unit|Floor|Fl\.)[ \t]*#?[A-Za-z0-9-]+)?"
)
_LABELLED_ADDR_RE = re.compile(
    r"(?:機關地址|通訊地址|營業所|住址|地址|Address)[ \t]*[:：][ \t]*([^\n]{4,120})",
    re.IGNORECASE,
)

# ---- PERSON (role-anchored only) ----
_ZH_ROLE = (
    "(?:專利代理人|發明人|創作人|設計人|申請人|代理人|專利師|聯絡人|承辦人|"
    "審查委員|審查官|審查人員|負責人|代表人|收件人|寄件人)"
)
_ZH_NAME = (
    rf"[{_CJK}]{{2,4}}?"
    r"(?=先生|小姐|女士|博士|教授|律師|專利師|[\s、，,。；;:：()（）\[\]/]|$)"
)
_ZH_PERSON_RE = re.compile(
    rf"{_ZH_ROLE}\s*[:：]\s*((?:{_ZH_NAME})(?:\s*[、，,及和與]\s*{_ZH_NAME})*)",
    re.MULTILINE,
)
_ZH_NAME_RE = re.compile(_ZH_NAME, re.MULTILINE)
_EN_ROLE = (
    r"\b(?:Inventors?|Applicants?|Attorneys?|Agents?|Examiners?|Contact|"
    r"Correspondent|Signed|Signature)"
)
_EN_NAME = r"[A-Z][A-Za-z'\-]*\.?(?: [A-Z][A-Za-z'\-]*\.?){0,5}"
_EN_PERSON_RE = re.compile(
    rf"{_EN_ROLE}(?:[ \t]+Name)?[ \t]*[:：][ \t]*"
    rf"({_EN_NAME}(?:[ \t]*(?:,|;|&|\band\b)[ \t]*{_EN_NAME})*)"
)
_EN_NAME_RE = re.compile(_EN_NAME)
# Tokens that follow a name on a signature line but are not part of it.
_EN_NAME_STOP = {
    "Esq",
    "Esq.",
    "Jr.",
    "Sr.",
    "PhD",
    "Ph.D.",
    "Email",
    "E-mail",
    "Tel",
    "Tel.",
    "Phone",
    "Fax",
    "Address",
    "Reg.",
    "No.",
    "REDACTED",
    "N/A",
}
# Words a role label can be followed by that are not a person's name.
_ZH_NOT_A_NAME = {
    "申請人",
    "發明人",
    "代理人",
    "如附件",
    "如文",
    "同上",
    "詳附件",
    "未指定",
}


def _en_name_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Trim trailing stop tokens (Esq., Email …); None if nothing is left."""
    tokens = list(re.finditer(r"\S+", text[start:end]))
    while tokens and tokens[-1].group(0) in _EN_NAME_STOP:
        tokens.pop()
    if not tokens or all(t.group(0) in _EN_NAME_STOP for t in tokens):
        return None
    return start + tokens[0].start(), start + tokens[-1].end()


def _trim_leading(text: str, start: int, end: int, words) -> tuple[int, int]:
    """Drop leading function words a greedy prefix swallowed."""
    changed = True
    while changed:
        changed = False
        for w in words:
            if text.startswith(w, start) and end - start > len(w):
                start += len(w)
                changed = True
    return start, end


def _rules_ner_spans(text: str) -> list[tuple[int, int, str]]:
    """Deterministic NER spans ``(start, end, PREFIX)`` over ``text``."""
    spans: list[tuple[int, int, str]] = []

    for m in _TW_ORG_RE.finditer(text):
        s, e = _trim_leading(text, m.start(), m.end(), _TW_ORG_LEAD_WORDS)
        # Need a >=2-char name before the legal-form suffix.
        suffix = re.search(_TW_ORG_SUFFIX + "$", text[s:e])
        if suffix and suffix.start() >= 2:
            spans.append((s, e, "ORG"))

    for m in _EN_ORG_RE.finditer(text):
        s, e = m.start(), m.end()
        while True:
            first = re.match(r"([A-Za-z]+)[ \t]+", text[s:e])
            if first and first.group(1) in _EN_LEAD_WORDS:
                s += first.end()
                continue
            break
        if re.search(r"[ \t]", text[s:e]):  # still "<Name> <suffix>"
            spans.append((s, e, "ORG"))

    for m in _TW_ADDR_RE.finditer(text):
        s, e = m.start(), m.end()
        lead = _TW_ADDR_LEAD.match(text[s:e])
        if lead:
            s += lead.end()
        if _TW_ADDR_MARKERS.search(text[s:e]):
            spans.append((s, e, "ADDRESS"))
    for m in _EN_ADDR_RE.finditer(text):
        spans.append((m.start(), m.end(), "ADDRESS"))
    for m in _LABELLED_ADDR_RE.finditer(text):
        s, e = m.start(1), m.end(1)
        while e > s and text[e - 1] in " \t":
            e -= 1
        spans.append((s, e, "ADDRESS"))

    for m in _ZH_PERSON_RE.finditer(text):
        for n in _ZH_NAME_RE.finditer(text, m.start(1), m.end(1)):
            if n.group(0) not in _ZH_NOT_A_NAME:
                spans.append((n.start(), n.end(), "PERSON"))
    for m in _EN_PERSON_RE.finditer(text):
        for n in _EN_NAME_RE.finditer(text, m.start(1), m.end(1)):
            span = _en_name_span(text, n.start(), n.end())
            if span:
                spans.append((span[0], span[1], "PERSON"))

    return spans


_ckip_driver = None
_ckip_unavailable = False
_ckip_lock = threading.Lock()


def _ckip_ner_spans(text: str) -> list[tuple[int, int, str]] | None:
    """ckip-transformers PERSON/ORG spans, or ``None`` when unavailable."""
    global _ckip_driver, _ckip_unavailable
    if _ckip_unavailable:
        return None
    try:
        with _ckip_lock:
            if _ckip_driver is None:
                from ckip_transformers.nlp import CkipNerChunker  # lazy, optional dep

                _ckip_driver = CkipNerChunker(
                    model=settings.NER_CKIP_MODEL, device=settings.NER_CKIP_DEVICE
                )
        spans: list[tuple[int, int, str]] = []
        # Line by line keeps each input well under the model's max length and
        # gives exact character offsets back into ``text``.
        offset = 0
        lines = text.split("\n")
        batch = [ln for ln in lines if ln.strip()]
        results = iter(_ckip_driver(batch, show_progress=False)) if batch else iter(())
        for ln in lines:
            if ln.strip():
                for ent in next(results):
                    if ent.ner in ("PERSON", "ORG"):
                        a, b = ent.idx
                        spans.append((offset + a, offset + b, ent.ner))
            offset += len(ln) + 1
        return spans
    except Exception as exc:  # noqa: BLE001 — optional backend must never break redact()
        _ckip_unavailable = True
        logger.warning(
            "NER_BACKEND=ckip unavailable (%s: %s) — falling back to rule-based NER.",
            exc.__class__.__name__,
            exc,
        )
        return None


def ner_spans(text: str, backend: str | None = None) -> list[tuple[int, int, str]]:
    """Resolved, non-overlapping NER spans for ``text`` (sorted by start).

    Spans touching an existing ``[RULE_XXXXXXXX]`` placeholder are dropped so
    redact() stays idempotent and never nests placeholders.
    """
    backend = (backend or settings.NER_BACKEND or "none").lower()
    if backend == "none":
        return []
    candidates = _rules_ner_spans(text)
    if backend == "ckip":
        candidates += _ckip_ner_spans(text) or []

    # Both interval sets are non-overlapping and kept sorted by start, so an
    # overlap with (s, e) can only be the last interval starting before e
    # (bisect): O(log n) per candidate instead of a scan of every chosen span
    # and placeholder — that scan made long texts quadratic (B-53).
    blocked = [(m.start(), m.end()) for m in _PLACEHOLDER_TOKEN_RE.finditer(text)]
    blocked_starts = [b[0] for b in blocked]

    def _hits(starts: list[int], ends: list[int], s: int, e: int) -> bool:
        i = bisect.bisect_left(starts, e)
        return i > 0 and ends[i - 1] > s

    blocked_ends = [b[1] for b in blocked]
    chosen: list[tuple[int, int, str]] = []
    chosen_starts: list[int] = []
    chosen_ends: list[int] = []
    for s, e, label in sorted(
        candidates, key=lambda c: (-_NER_PRIORITY[c[2]], -(c[1] - c[0]), c[0])
    ):
        if e - s < 2 or not text[s:e].strip():
            continue
        if _hits(blocked_starts, blocked_ends, s, e):
            continue
        if _hits(chosen_starts, chosen_ends, s, e):
            continue
        i = bisect.bisect_left(chosen_starts, s)
        chosen_starts.insert(i, s)
        chosen_ends.insert(i, e)
        chosen.append((s, e, label))
    return sorted(chosen)


# --- At-rest encryption of the un-redaction table (Q3/Q10) ---

# Domain-separation constants for key derivation.
_HKDF_INFO_PREFIX = b"patentmind/mapping-encryption/v1/tenant="
_HKDF_SALT = b"patentmind-mapping-store"

# Emit the "no master key" boot guard once per process, not per derivation.
_dev_key_warned = False


def _master_key_bytes() -> bytes:
    """Resolve the master key for mapping-table encryption.

    Mirrors the JWT_SECRET boot-guard style: production MUST provide a real
    secret via ``MAPPING_ENCRYPTION_KEY``. For the POC / pytest / demo we derive
    a deterministic dev key so the system runs out of the box, but we log a
    WARNING (once) so the gap is visible. We DO NOT hard-fail (the demo must run).
    """
    global _dev_key_warned
    configured = (settings.MAPPING_ENCRYPTION_KEY or "").strip()
    if configured:
        return configured.encode("utf-8")

    if not _dev_key_warned:
        logger.warning(
            "MAPPING_ENCRYPTION_KEY is not set — deriving a deterministic DEV "
            "key for the redaction mapping table. The un-redaction map is the "
            "crown jewel; set MAPPING_ENCRYPTION_KEY to a real secret in "
            "production."
        )
        _dev_key_warned = True
    # Deterministic dev fallback so redact/unmask round-trips reproducibly in
    # the POC. Tied to JWT_SECRET only to vary across local installs; this is
    # explicitly NOT production-grade.
    return hashlib.sha256(
        b"patentmind-dev-mapping-master::" + settings.JWT_SECRET.encode("utf-8")
    ).digest()


def _tenant_fernet(tenant_id: str) -> Fernet:
    """Derive a per-tenant Fernet key from the master key via HKDF-SHA256.

    A tenant's ciphertext is only decryptable with that tenant's derived key, so
    a leaked single-tenant table cannot be cross-decrypted with another tenant's
    key (tenant isolation at rest).
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO_PREFIX + tenant_id.encode("utf-8"),
    )
    raw = hkdf.derive(_master_key_bytes())
    return Fernet(base64.urlsafe_b64encode(raw))


# --- Mapping table (LOCAL ONLY, never uploaded; `original` encrypted at rest) ---


# --- Per-data-subject lookup (Q27 — GDPR / 個資法 right-to-erasure) ---
#
# The mapping table used to be keyed only by (tenant_id, placeholder), so a
# request "erase everything about 0912-345-678" could not be served short of
# wiping the whole tenant. Each row now carries ``subject_hmac`` — a KEYED hash
# of the normalised original value (never the plaintext; a bare hash of a phone
# number would be brute-forceable, see _stable_id). Erasure recomputes the HMAC
# of the values the data subject supplies and deletes the matching rows, which
# makes their placeholders permanently irreversible.


def normalize_subject_value(value: str) -> str:
    """Canonical form used for subject lookup: detection-normalised, casefolded,
    with whitespace / dashes / parentheses removed (so ``0912-345-678`` and
    ``0912 345 678`` locate the same subject)."""
    return re.sub(r"[\s\-()]", "", normalize_for_detection(value).casefold())


def subject_hmac(tenant_id: str, value: str) -> str:
    key = hashlib.sha256(b"patentmind-subject-lookup::" + _master_key_bytes()).digest()
    msg = f"{tenant_id}:{normalize_subject_value(value)}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _looks_like_fernet(token: str) -> bool:
    return token.startswith("gAAAAA")


def migrate_mapping_db(conn: sqlite3.Connection) -> int:
    """Idempotent schema migration for a mapping DB (live store OR a file
    opened by backup.py). Creates the table if missing, adds + indexes the
    ``subject_hmac`` column, and backfills rows that lack it by decrypting
    per tenant. A legacy PLAINTEXT row (pre-encryption era) is re-encrypted in
    the same pass so no plaintext PII stays at rest. Returns rows backfilled.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mappings (
            tenant_id TEXT NOT NULL,
            placeholder TEXT NOT NULL,
            original TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            subject_hmac TEXT,
            PRIMARY KEY (tenant_id, placeholder)
        )
        """
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mappings)")}
    if "subject_hmac" not in cols:
        conn.execute("ALTER TABLE mappings ADD COLUMN subject_hmac TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mappings_subject ON mappings(tenant_id, subject_hmac)"
    )
    rows = conn.execute(
        "SELECT tenant_id, placeholder, original FROM mappings WHERE subject_hmac IS NULL"
    ).fetchall()
    backfilled = 0
    for tenant_id, placeholder, stored in rows:
        fernet = _tenant_fernet(tenant_id)
        try:
            plaintext = fernet.decrypt(stored.encode("ascii")).decode("utf-8")
            new_stored = stored
        except (InvalidToken, ValueError, UnicodeDecodeError, UnicodeEncodeError):
            if _looks_like_fernet(stored):
                # Ciphertext under another key: cannot index it; leave NULL
                # (reported as un-locatable by erase_subject).
                continue
            plaintext = stored  # legacy plaintext row → encrypt it now
            new_stored = fernet.encrypt(stored.encode("utf-8")).decode("ascii")
        conn.execute(
            "UPDATE mappings SET subject_hmac = ?, original = ? "
            "WHERE tenant_id = ? AND placeholder = ?",
            (subject_hmac(tenant_id, plaintext), new_stored, tenant_id, placeholder),
        )
        backfilled += 1
    conn.commit()
    return backfilled


class MaskingStore:
    """Append-only local mapping table.  Reversible un-mask for inbound responses.

    The `original` column stores per-tenant-encrypted ciphertext (urlsafe-b64
    Fernet token), never plaintext PII. `subject_hmac` is a keyed lookup hash
    of the original (Q27 per-subject erasure).
    """

    def __init__(self, path: Path = MAPPING_DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        migrate_mapping_db(self._conn)

    def remember(self, tenant_id: str, placeholder: str, original: str, rule_id: str):
        self.remember_many(tenant_id, [(placeholder, original, rule_id)])

    def remember_many(self, tenant_id: str, entries: list[tuple[str, str, str]]) -> None:
        """Store (placeholder, original, rule_id) rows in ONE transaction.

        BE-7: one commit per redacted text, not one per entity — an OA with
        thirty entities used to pay thirty journal syncs, under a lock every
        concurrent analysis shares.
        """
        if not entries:
            return
        fernet = _tenant_fernet(tenant_id)
        # Encrypt the original under the tenant-derived key BEFORE it touches disk.
        rows = [
            (
                tenant_id,
                placeholder,
                fernet.encrypt(original.encode("utf-8")).decode("ascii"),  # TEXT-safe token
                rule_id,
                subject_hmac(tenant_id, original),
            )
            for placeholder, original, rule_id in entries
        ]
        with self._lock:
            try:
                self._conn.executemany(
                    "INSERT OR IGNORE INTO mappings"
                    "(tenant_id, placeholder, original, rule_id, subject_hmac) "
                    "VALUES (?, ?, ?, ?, ?)",
                    rows,
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()  # no half batch left open on the shared connection
                raise

    def ping(self) -> None:
        """Readiness (OBS-9): the mapping store answers — without it nothing
        can be redacted, so nothing can be analysed."""
        with self._lock:
            self._conn.execute("SELECT 1 FROM mappings LIMIT 1").fetchall()

    def get_original(self, tenant_id: str, placeholder: str) -> str | None:
        # The connection is shared by every request thread (unmask now runs
        # off the event loop) — one statement at a time.
        with self._lock:
            row = self._conn.execute(
                "SELECT original FROM mappings WHERE tenant_id = ? AND placeholder = ?",
                (tenant_id, placeholder),
            ).fetchone()
        if not row:
            return None
        stored = row[0]
        try:
            plaintext = _tenant_fernet(tenant_id).decrypt(stored.encode("ascii"))
            return plaintext.decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError):
            # Wrong tenant key, tampered/corrupt ciphertext, or a stray legacy
            # plaintext row. Degrade gracefully: never crash un-redaction, and
            # never leak an undecryptable original. The caller (unmask) keeps the
            # placeholder when None is returned.
            logger.warning(
                "Failed to decrypt mapping for tenant=%s placeholder=%s; "
                "returning placeholder unchanged.",
                tenant_id,
                placeholder,
            )
            return None


_store = MaskingStore()


def _stable_id(text: str, salt: str) -> str:
    """Generate deterministic short id so same value → same placeholder per tenant.

    Lets LLM reason about co-occurrence (same email shows up twice = related)
    without ever seeing the real value.
    """
    # Keyed HMAC, not a bare hash: placeholders reach the cloud LLM, and an
    # unkeyed sha256(tenant:value) over a small space (a TW mobile number is
    # 10^8 candidates) is brute-forced back to the PII in minutes. The key is
    # derived from the on-prem mapping master key, so only the gateway can
    # recompute it.
    key = hashlib.sha256(b"patentmind-placeholder-id::" + _master_key_bytes()).digest()
    return hmac.new(key, f"{salt}:{text}".encode(), hashlib.sha256).hexdigest()[:8].upper()


_DETECTION_CHUNK = 4096


def detection_length(text: str, limit: int | None = None) -> int:
    """How much text masking will actually scan, for size caps (B-53).

    ``redact`` works on ``normalize_for_detection(text)``, and NFKC can
    expand one character up to 18-fold (U+FDFA), so a cap on the raw length
    alone let 96k characters become 1.7M. Never less than the raw length.

    Bounded work (B-54): text already in NFKC form cannot grow (confusable
    folding is one character to one, zero-width stripping only removes), so
    it costs one quick check; otherwise the text is normalised in chunks and
    counting stops as soon as ``limit`` is passed — the caller only needs
    to know it is over its cap. (Normalising all of it took seconds, before
    the rate limit could refuse the request.) A combining sequence split at
    a chunk border may count a character differently: fine for a cap.
    """
    if unicodedata.is_normalized("NFKC", text):
        return len(text)
    total = 0
    for i in range(0, len(text), _DETECTION_CHUNK):
        total += len(normalize_for_detection(text[i : i + _DETECTION_CHUNK]))
        if limit is not None and total > limit:
            break
    return max(len(text), total)


def redact(text: str, tenant_id: str) -> tuple[str, list[str]]:
    """Replace all matches with reversible placeholders.

    Returns (redacted_text, list_of_rule_ids_triggered).

    Q11 spotlight handling is in oa_analyzer; this layer is purely pattern-based.

    Unicode normalisation (M-6 fix + Day 12A hardening)
    ---------------------------------------------------
    The input is canonicalised via ``normalize_for_detection`` BEFORE any
    regex applies:  zero-width strip → confusable fold → **NFKC**. The first
    two steps close evasions NFKC alone does NOT (invisible token-splitting
    and cross-script homoglyphs); see ``normalize_for_detection`` and the
    module-level threat-model comment. The NFKC step then handles the
    compatibility classes described below.

    The regex tables target ASCII characters (``a-zA-Z``,
    ``0-9``, ``@``, ``-``); without normalisation, mixed-script inputs
    bypass them entirely:

    * Fullwidth digits ``０９１２`` (U+FF10..FF19) match no ``\\d`` class
      built from ASCII brackets — a fullwidth-typed Taiwan mobile number
      slips past ``phone_tw``.
    * Halfwidth/fullwidth ligatures (e.g. ``＠`` U+FF20 for ``@``) bypass
      the email regex.
    * Compatibility decompositions (e.g. ``ｆｉ`` U+FB01 → ``fi``) bypass
      any literal substring rules a tenant dictionary might add.

    NFKC folds all these variants into their canonical ASCII forms so the
    existing regex inventory keeps working without per-rule
    Unicode-aware rewrites (which would have to be re-audited every time
    a tenant adds a rule).

    Why **NFKC** and not NFC?

    * NFC only handles canonical equivalence (composed vs decomposed
      diacritics) — it would catch the NFD-typed email case
      (``a\\u0301lice@…`` → ``álice@…``) but NOT fullwidth digits, which
      are a deliberate threat-model entry: a Taiwanese user pasting from
      a Word document that auto-corrected to fullwidth would leak phone
      numbers.
    * NFKC is a superset of NFC plus compatibility folding (fullwidth →
      halfwidth, ligatures → components, superscripts → bases). It's
      lossy in the sense that ``Ⅳ`` becomes ``IV`` — that loss is
      exactly what we want for PII detection (a roman numeral 4 in a
      patent claim is informationally identical to ``IV``).

    The mapping table stores the **normalised** form as the original, so
    when ``unmask`` reverses the placeholder it returns the canonical
    spelling. For the demo this is fine; a future refinement could keep a
    side-table mapping back to the raw bytes if any caller needs the
    pre-normalisation form (the OA preview UI does NOT — it shows the
    redaction overlay over the normalised view).
    """
    triggered: list[str] = []
    # M-6 + Day 12A: canonicalise input. ``text`` becomes the
    # zero-width-stripped + confusable-folded + NFKC form going forward; all
    # downstream operations (regex matching, placeholder storage, round-trip
    # through ``unmask``) work on this canonical form. See
    # ``normalize_for_detection`` for the (load-bearing) ordering rationale.
    redacted = normalize_for_detection(text)

    # Layer 1 (built-in PII) + layer 2 (per-tenant uploadable dictionary, with
    # hard-coded fallback). Same merge order as before; the tenant layer-2 set
    # is now loaded + cached from data/tenant_dicts/<tenant_id>.json.
    rules = list(PII_RULES) + get_tenant_rules(tenant_id)
    # placeholder → (original, rule_id); written in one transaction below,
    # before the redacted text is returned (so before it can leave the
    # gateway, and unmask always finds its mapping).
    pending: dict[str, tuple[str, str]] = {}

    for rule in rules:
        # `rule=rule` binds the loop variable at definition time (B023). The
        # closure is only ever invoked inside this iteration's `.sub(...)`
        # call below, so behaviour is identical — this just makes it explicit.
        def _sub(match: re.Match, rule=rule) -> str:
            original = match.group(0)
            sid = _stable_id(original, salt=tenant_id)
            placeholder = f"[{rule.placeholder_prefix}_{sid}]"
            pending.setdefault(placeholder, (original, rule.rule_id))
            if rule.rule_id not in triggered:
                triggered.append(rule.rule_id)
            return placeholder

        redacted = rule.pattern.sub(_sub, redacted)

    # Layer 3 (Q25): named entities — person / organisation / address. Runs on
    # the placeholder-bearing text; spans overlapping a placeholder are skipped.
    # Built as a list and joined once: rebuilding the whole string per span
    # was quadratic in the number of entities (B-53). `triggered` keeps the
    # order the old reversed() walk produced.
    spans = ner_spans(redacted)
    for _start, _end, label in reversed(spans):
        rule_id = _NER_RULE_IDS[label]
        if rule_id not in triggered:
            triggered.append(rule_id)
    pieces: list[str] = []
    cursor = 0
    for start, end, label in spans:
        original = redacted[start:end]
        sid = _stable_id(original, salt=tenant_id)
        placeholder = f"[{label}_{sid}]"
        pending.setdefault(placeholder, (original, _NER_RULE_IDS[label]))
        pieces.append(redacted[cursor:start])
        pieces.append(placeholder)
        cursor = end
    if spans:
        pieces.append(redacted[cursor:])
        redacted = "".join(pieces)

    _store.remember_many(
        tenant_id, [(placeholder, original, rule_id) for placeholder, (original, rule_id) in pending.items()]
    )
    return redacted, triggered


def unmask(text: str, tenant_id: str) -> str:
    """Reverse redaction for inbound responses.  Server-side only."""
    placeholder_pattern = re.compile(r"\[([A-Z_]+)_([0-9A-F]{8})\]")

    def _sub(match: re.Match) -> str:
        placeholder = match.group(0)
        original = _store.get_original(tenant_id, placeholder)
        return original if original is not None else placeholder

    return placeholder_pattern.sub(_sub, text)
