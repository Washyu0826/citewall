"""OA mailing/issue-date extraction (the start event of every statutory
deadline). A wrong pick — today's date, or the application's filing date —
silently shifts the deadline, so the label-first rules are pinned here."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from backend.ai_engine.oa_analyzer import extract_received_date

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "oa_samples"


@pytest.mark.parametrize(
    "fname,expected",
    [
        ("sample_oa_tw.txt", date(2025, 5, 29)),  # 發文日期：中華民國 114 年 5 月 29 日
        ("sample_oa_us.txt", date(2025, 4, 15)),  # Mailing Date: 2025-04-15
        ("sample_oa_cn.txt", date(2025, 4, 15)),  # 发文日：2025年04月15日
        ("sample_oa_kr.txt", date(2025, 4, 15)),  # 발송일: 2025년 04월 15일
        ("sample_oa_ep.txt", date(2025, 4, 15)),  # Date of this communication: 2025-04-15
    ],
)
def test_shipped_samples(fname, expected):
    got = extract_received_date((SAMPLES / fname).read_text(encoding="utf-8"))
    assert got is not None and got.date() == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        # TW: a filing date (申請日) appearing first must NOT be picked.
        ("申請日為 113 年 10 月 30 日。\n發文日期：中華民國 114 年 5 月 29 日", date(2025, 5, 29)),
        ("申請日：民國113年10月30日　本局中華民國114年5月29日函", date(2025, 5, 29)),
        # US variants
        ("Filing Date: 2024-01-02\nDate mailed: 04/15/2025", date(2025, 4, 15)),
        ("Notification Date: April 15, 2025", date(2025, 4, 15)),
        ("Filing Date: 01/02/2024\nNotification Date: 2025/04/15", date(2025, 4, 15)),
        # CN / KR labelled
        ("申请日：2024年01月02日\n发文日：2025年04月15日", date(2025, 4, 15)),
        ("출원일: 2024년 01월 02일\n발송일: 2025년 04월 15일", date(2025, 4, 15)),
        # Unlabelled fallback: first non-filing date
        ("Ref x — 2025-03-01 — see attached", date(2025, 3, 1)),
    ],
)
def test_label_first_and_never_filing_date(text, expected):
    got = extract_received_date(text)
    assert got is not None and got.date() == expected


@pytest.mark.parametrize(
    "text", ["", "no dates here", "Filed 2024-01-02 only", "申請日：2024年01月02日"]
)
def test_returns_none_rather_than_a_filing_date(text):
    assert extract_received_date(text) is None
