"""Masking stays (close to) linear on adversarial input (FAILURE_LOG B-53).

Before the fix, on this kind of input (wall-clock on the dev laptop):
  * 3,000 spaces took ~50 s in the Taiwan-address pattern (nested ``\\s*``);
  * a 96k-character run of e-mail local-part characters took ~10 s;
  * 96k characters of "Ab, " after a role label took ~33 s in the NER overlap
    check (every candidate scanned every chosen span).
Each case now takes well under a second. The limits below leave a wide margin
for slow CI runners, and a regression would still fail them by an order of
magnitude (rather than hang: the slowest old case finishes in about a minute).
"""

from __future__ import annotations

import time

import pytest

from backend.gateway import masking

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
    ],
    ids=[
        "spaces-3k",
        "spaces-cap",
        "local-part-run",
        "digit-dash",
        "en-names",
        "zh-names",
        "addr-run",
    ],
)
def test_redact_is_fast_on_adversarial_input(text, limit_s):
    _, elapsed = _timed(masking.redact, text, "tenant_a")
    assert elapsed < limit_s, f"{elapsed:.2f}s"


def test_an_address_match_still_starts_at_the_whitespace_run():
    # The linear pattern may start inside a whitespace run only at its first
    # character — exactly where the old (leftmost) match started. Pin it: a
    # "never start at whitespace" shortcut would change the masked text.
    text = "在  中山路12號3樓"
    spans = [(m.start(), m.end()) for m in masking._TW_ADDR_RE.finditer(text)]
    assert spans == [(1, len(text))]


def test_two_emails_back_to_back_are_both_masked():
    # Why the e-mail pattern is bounded rather than "start of run only".
    redacted, rules = masking.redact("a@b.com1x@y.com", "tenant_a")
    assert "@" not in redacted
    assert redacted.count("[EMAIL_") == 2
    assert rules == ["email"]


def test_an_overlong_local_part_still_masks_the_address():
    # RFC 5321 caps the local part at 64; the pattern takes the last 64.
    redacted, _ = masking.redact("x" * 100 + "@example.com", "tenant_a")
    assert "@" not in redacted and "example.com" not in redacted


def test_detection_length_counts_nfkc_expansion():
    assert masking.detection_length("abc") == 3
    # U+FDFA normalises to 18 characters.
    assert masking.detection_length("\ufdfa" * 10) == 180
