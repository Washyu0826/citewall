"""Masking stays (close to) linear on adversarial input (FAILURE_LOG B-53..B-56).

Before the fixes, on this kind of input (wall-clock on the dev laptop):
  * 3,000 spaces took ~50 s in the Taiwan-address pattern (nested ``\\s*``);
  * a 96k-character run of e-mail local-part characters took ~10 s;
  * 96k characters of "Ab, " after a role label took ~33 s in the NER overlap
    check (every candidate scanned every chosen span);
  * "Passport" / "統編" followed by 16k spaces took ~4.6 s (two ``\\s*`` around
    an optional marker), and "A.A.A.…" took ~24 s at 96k in the English
    organisation pattern (B-54, found by the second review).
The super-linear cases now take a fraction of a second, and putting any of
those rules back fails these limits by an order of magnitude (rather than
hang: the slowest old case finishes in about a minute). The address
"prefixes + digits" case is different: linear but expensive (~1–1.5 s at
the cap); its possessive digit runs are a constant-factor improvement
(~3.5 s before) that these timings do NOT guard (B-55). "en-org-long-words"
guards a linear blow-up the ratio scan below cannot see: the B-55 English
organisation pattern retried a second branch for each of six words — 2^6
paths per start, ~5 s at the cap; ~0.2 s since B-56.

``test_no_masking_rule_grows_superlinearly`` is the systematic guard: every
masking regex — built-in, NER and tenant dictionaries — against families of
"label + long run" inputs, at a size where an O(n²) rule is already slow.
"""

from __future__ import annotations

import os
import re
import time

import pytest

from backend.gateway import masking
from backend.shared.config import TENANT_DICTS_DIR

_CAP_CHARS = 95_999  # just under the 32k-token analysis cap (chars // 3)


@pytest.fixture(autouse=True)
def _no_mapping_writes(monkeypatch):
    class _NoStore:
        def remember_many(self, *a, **k):
            pass

    monkeypatch.setattr(masking, "_store", _NoStore())


def _fill(unit: str, n: int) -> str:
    return (unit * (n // len(unit) + 1))[:n]


def _timed(fn, *args):
    started = time.perf_counter()
    result = fn(*args)
    return result, time.perf_counter() - started


@pytest.mark.parametrize(
    "text, limit_s",
    [
        (_fill(" ", 3_000), 1.0),  # was ~50 s (address pattern)
        (_fill(" ", _CAP_CHARS), 2.0),
        (_fill("a", _CAP_CHARS), 3.0),  # was ~10 s (email)
        (_fill("1-", _CAP_CHARS), 3.0),
        ("Applicant: " + _fill("Ab, ", _CAP_CHARS), 4.0),  # was ~33 s (NER overlaps)
        ("申請人：" + _fill("王、", _CAP_CHARS), 4.0),
        (_fill("台北市中正區", _CAP_CHARS), 4.0),
        ("Passport" + _fill(" ", _CAP_CHARS) + "x", 2.0),  # was ~140 s (B-54)
        ("統編" + _fill("\n", _CAP_CHARS) + "x", 2.0),
        ("Tax ID" + _fill("\t", _CAP_CHARS) + "x", 2.0),
        (_fill("A.", _CAP_CHARS), 3.0),  # was ~24 s (English organisation, B-54)
        ("市" * 18 + "路" + _fill("1", _CAP_CHARS), 6.0),  # linear but expensive (~0.8-1 s)
        (_fill("a@b.com1", _CAP_CHARS), 3.0),
        (_fill(("A." * 128)[:255] + "A ", _CAP_CHARS), 1.5),  # was ~5 s (B-56)
    ],
    ids=[
        "spaces-3k",
        "spaces-cap",
        "local-part-run",
        "digit-dash",
        "en-names",
        "zh-names",
        "addr-run",
        "passport-spaces",
        "taxid-newlines",
        "taxid-tabs",
        "en-org-dots",
        "addr-prefixes-digits",
        "glued-emails",
        "en-org-long-words",
    ],
)
def test_redact_is_fast_on_adversarial_input(text, limit_s):
    _, elapsed = _timed(masking.redact, text, "tenant_a")
    assert elapsed < limit_s, f"{elapsed:.2f}s"


def _all_masking_patterns() -> dict[str, re.Pattern]:
    patterns = {f"pii:{r.rule_id}": r.pattern for r in masking.PII_RULES}
    # The egress guard's cheaper existence patterns run on every payload too.
    for r in masking.PII_RULES:
        if r.search_pattern is not None:
            patterns[f"pii-search:{r.rule_id}"] = r.search_pattern
    for name in os.listdir(TENANT_DICTS_DIR):
        if name.endswith(".json"):
            for r in masking.get_tenant_rules(name[:-5]):
                patterns.setdefault(f"tenant:{r.rule_id}", r.pattern)
    for name in dir(masking):
        obj = getattr(masking, name)
        if isinstance(obj, re.Pattern):
            patterns[f"re:{name}"] = obj
    return patterns


_LABELS = ["", "Passport No.", "護照號碼", "營利事業統一編號", "Tax ID", "Uniform Business No", "Applicant:", "申請人：",
           "地址：", "台北市", "中山路", "Acme ", "+886", "x@"]  # fmt: skip
_RUNS = [" ", "\t", "\n", "a", "A", "1", ".", "-", "A.", "A-", "1 ", "Ab ", "中", "市", "、", "a.b", "1:"]


def _scan_seconds(pattern: re.Pattern, text: str, repeat: int = 1) -> float:
    """Fastest of ``repeat`` runs: a one-off preemption on a busy CI runner
    must not look like super-linear growth (B-55)."""
    best = float("inf")
    for _ in range(repeat):
        started = time.perf_counter()
        for _ in pattern.finditer(text):
            pass
        best = min(best, time.perf_counter() - started)
    return best


@pytest.mark.parametrize("name", sorted(_all_masking_patterns()))
def test_no_masking_rule_grows_superlinearly(name):
    """Every (label, run) family at 2k and 8k characters. Four times the input
    must cost about four times the time: an O(n²) rule costs ~16x (the old
    passport rule: 0.06 s -> 1.0 s; English organisation: 0.009 s -> 0.15 s).
    Only families that are measurably slow at 8k are judged (timer noise)."""
    pattern = _all_masking_patterns()[name]
    for label in _LABELS:
        for run in _RUNS:
            big_text = masking.normalize_for_detection(label + _fill(run, 8_000) + "x")
            if _scan_seconds(pattern, big_text) < 0.03:
                continue
            big = _scan_seconds(pattern, big_text, repeat=3)
            small = _scan_seconds(
                pattern, masking.normalize_for_detection(label + _fill(run, 2_000) + "x"), repeat=3
            )
            ratio = big / max(small, 1e-6)
            assert ratio < 9, f"{name}: x{ratio:.1f} ({small:.3f}s -> {big:.3f}s) on {label!r} + {run!r}*n"


def test_an_address_match_still_starts_at_the_whitespace_run():
    # The linear pattern may start inside a whitespace run only at its first
    # character — exactly where the old (leftmost) match started. Pin it: a
    # "never start at whitespace" shortcut would change the masked text.
    text = "在  中山路12號3樓"
    spans = [(m.start(), m.end()) for m in masking._TW_ADDR_RE.finditer(text)]
    assert spans == [(1, len(text))]


def test_two_emails_back_to_back_are_both_masked():
    # Why the e-mail pattern is not simply "start of run only".
    redacted, rules = masking.redact("a@b.com1x@y.com", "tenant_a")
    assert "@" not in redacted
    assert redacted.count("[EMAIL_") == 2
    assert rules == ["email"]


def test_a_long_local_part_glued_to_a_previous_address_is_still_masked():
    # B-54: the first bounded version (64) left the leading characters of such
    # a local part unmasked. Up to 256 is masked whole.
    second = "x" * 200 + "@y.com"
    redacted, _ = masking.redact("a@b.co_" + second, "tenant_a")
    assert "x" not in redacted and "@" not in redacted


def test_an_overlong_local_part_still_masks_the_address():
    redacted, _ = masking.redact("x" * 300 + "@example.com", "tenant_a")
    assert "@" not in redacted and "example.com" not in redacted and "x" not in redacted


def test_detection_length_counts_nfkc_expansion():
    assert masking.detection_length("abc") == 3
    # U+FDFA normalises to 18 characters.
    assert masking.detection_length("\ufdfa" * 10) == 180


def test_detection_length_stops_past_the_limit():
    # B-54: normalising everything took seconds before the rate limit could
    # refuse the request. With a limit it stops just past it.
    text = "\ufdfa" * _CAP_CHARS
    n, elapsed = _timed(masking.detection_length, text, 96_003)
    # Past the limit, but by at most one chunk's worth (4,096 x 18) — not the
    # whole 1.7M: the work is bounded by the cap, not by what was sent.
    assert 96_003 < n <= 96_003 + 4_096 * 18
    assert elapsed < 0.5, f"{elapsed:.2f}s"


@pytest.mark.parametrize(
    "lead, length",
    [("by ", 300), ("x.", 100), ("e-", 200), ("x.", 256), ("Foo Inc.", 120)],
    ids=["run-start-300", "inside-run-100", "inside-run-200", "inside-run-256", "after-previous-match-120"],
)
def test_a_long_organisation_word_is_still_masked_whole(lead, length):
    # B-55: the first fix (64 for every word) left such names unmasked or
    # half-masked; a word from the start of its run is unbounded, one starting
    # inside a run is bounded at 256 (the test below pins both sides).
    name = "S" + "upercalifragilistic" * (length // 19 + 1)
    name = name[:length]
    redacted, rules = masking.redact(f"{lead}{name} Corp. signed", "tenant_a")
    assert "upercalifragilistic" not in redacted, redacted[:120]
    assert "ner_org" in rules


def test_the_inside_run_bound_is_256_exactly():
    # B-57: a word that starts inside a run (here after "x.") is matched up
    # to 256 characters and no further — the bound that keeps the work per
    # start constant. A larger bound would pass the masking tests above and
    # only cost time; a smaller one would under-mask (B-55).
    def word(n):
        return "S" + "u" * (n - 1)  # one capital: no other start inside the word

    assert masking._EN_ORG_RE.search(f"x.{word(256)} Corp.") is not None
    assert masking._EN_ORG_RE.search(f"x.{word(257)} Corp.") is None
    # From the start of a run the word is unbounded.
    assert masking._EN_ORG_RE.search(f"by {word(1000)} Corp.") is not None
