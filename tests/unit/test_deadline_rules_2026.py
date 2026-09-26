"""Deadline decisions Q16–Q21 (2026-09-25) and the 2026/2027 calendars.

Q16  JP: domestic 60 days / overseas 3 months; unknown -> 60 days + note.
Q17  CN: first OA 4 months, 2nd+ 2 months (detected from the text); unknown
     -> 2 months + note.
Q18  TW: 2 months kept, with a note that overseas applicants may get 3.
Q19  start from service: explicit / labelled service date, CN presumed
     mailing + 15 days, else mailing date + note. US/EP/JP run from mailing.
Q20  2026/2027 calendars incl. CN 调休 make-up working weekends.
Q21  every result says rules_reviewed=False.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from backend.ai_engine.deadline import (
    CALENDARS_DIR,
    RULES,
    calculate_deadline,
    detect_cn_oa_sequence,
    detect_cn_stated_months,
    extract_service_date,
    get_holidays,
    get_workdays,
    resolve_calendar,
)


def _utc(y, m, d, hh=12):
    # 12:00 UTC is the same calendar day in every case zone (New York..Tokyo).
    return datetime(y, m, d, hh, 0, tzinfo=UTC)


def _stat(r) -> date:
    return date.fromisoformat(r["statutory_deadline"][:10])


def _notes(r) -> str:
    return " | ".join(r["assumptions"])


# --------------------------------------------------------------------------- #
# Q16 — JP applicant domicile
# --------------------------------------------------------------------------- #


def test_jp_domestic_is_60_days_without_note():
    # 2026-06-01 + 60 days = 2026-07-31 (Fri)
    r = calculate_deadline(_utc(2026, 6, 1), "JP", applicant_domestic=True)
    assert _stat(r) == date(2026, 7, 31)
    assert r["period_applied"] == "60 days (domestic applicant)"
    assert r["assumptions"] == []


def test_jp_overseas_is_3_calendar_months():
    r = calculate_deadline(_utc(2026, 6, 1), "JP", applicant_domestic=False)
    assert _stat(r) == date(2026, 9, 1)
    assert r["period_applied"] == "3 months (overseas applicant)"


def test_jp_unknown_domicile_takes_earlier_60_days_and_says_so():
    unknown = calculate_deadline(_utc(2026, 6, 1), "JP")
    domestic = calculate_deadline(_utc(2026, 6, 1), "JP", applicant_domestic=True)
    overseas = calculate_deadline(_utc(2026, 6, 1), "JP", applicant_domestic=False)
    assert _stat(unknown) == _stat(domestic) < _stat(overseas)
    assert "domicile unknown" in _notes(unknown)
    assert any("domicile unknown" in w for w in unknown["warnings"])


def test_jp_counts_from_mailing_even_if_service_date_given():
    """JPO periods run from 発送日; a later service date must not extend them."""
    r = calculate_deadline(
        _utc(2026, 6, 1), "JP", applicant_domestic=True, service_date=date(2026, 6, 5)
    )
    assert r["start_date"] == "2026-06-01"
    assert r["start_date_basis"] == "mailing_date"


# --------------------------------------------------------------------------- #
# Q17 — CN Office Action sequence
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text,expected",
    [
        ("第一次审查意见通知书", 1),
        ("第二次审查意见通知书", 2),
        ("第 3 次审查意见通知书", 3),
        ("第十一次審查意見通知書", 11),
        ("第十次审查意见通知书", 10),
        ("审查意见通知书", None),
        ("", None),
        (None, None),
    ],
)
def test_detect_cn_oa_sequence(text, expected):
    assert detect_cn_oa_sequence(text) == expected


def test_cn_first_oa_is_4_months_from_presumed_service():
    # mailing 2026-03-02 -> presumed service 2026-03-17 -> +4 months 2026-07-17 (Fri)
    r = calculate_deadline(_utc(2026, 3, 2), "CN", oa_sequence=1)
    assert r["start_date"] == "2026-03-17"
    assert r["start_date_basis"] == "presumed_service"
    assert _stat(r) == date(2026, 7, 17)
    assert r["period_applied"] == "4 months (first Office Action)"


def test_cn_second_oa_is_2_months():
    r = calculate_deadline(_utc(2026, 3, 2), "CN", oa_sequence=2)
    assert _stat(r) == date(2026, 5, 18)  # 5/17 is a Sunday -> Mon 5/18
    assert r["period_applied"] == "2 months (Office Action #2)"


def test_cn_sequence_auto_detected_from_oa_text():
    first = calculate_deadline(
        _utc(2026, 3, 2), "CN", oa_text="国家知识产权局\n第一次审查意见通知书\n"
    )
    second = calculate_deadline(_utc(2026, 3, 2), "CN", oa_text="第二次审查意见通知书")
    assert first["period_applied"].startswith("4 months")
    assert second["period_applied"].startswith("2 months")
    assert "sequence unknown" not in _notes(first)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("请申请人自本通知书发文日起四个月内陈述意见", 4),
        ("自收到本通知书之日起两个月内答复", 2),
        ("自發文日起2個月內", 2),
        ("四个月", None),
        (None, None),
    ],
)
def test_detect_cn_stated_months(text, expected):
    assert detect_cn_stated_months(text) == expected


def test_cn_period_stated_in_notice_wins_over_inference():
    text = "第二次审查意见通知书\n请申请人自本通知书发文日起四个月内陈述意见"
    r = calculate_deadline(_utc(2026, 3, 2), "CN", oa_text=text)
    assert r["period_applied"] == "4 months (stated in the notice)"
    assert "sequence unknown" not in _notes(r)


def test_cn_explicit_sequence_wins_over_stated_period():
    text = "请申请人自本通知书发文日起四个月内陈述意见"
    r = calculate_deadline(_utc(2026, 3, 2), "CN", oa_sequence=2, oa_text=text)
    assert r["period_applied"] == "2 months (Office Action #2)"


def test_cn_unknown_sequence_takes_earlier_2_months_and_says_so():
    r = calculate_deadline(_utc(2026, 3, 2), "CN")
    assert r["period_applied"] == "2 months (sequence unknown; assumed 2nd+)"
    assert "sequence unknown" in _notes(r)
    first = calculate_deadline(_utc(2026, 3, 2), "CN", oa_sequence=1)
    assert _stat(r) < _stat(first)


# --------------------------------------------------------------------------- #
# Q18 — TW overseas-applicant hint
# --------------------------------------------------------------------------- #


def test_tw_keeps_2_months_and_warns_about_overseas_applicants():
    r = calculate_deadline(_utc(2026, 3, 2), "TW", service_date=date(2026, 3, 4))
    assert r["period_applied"] == "2 months"
    assert _stat(r) == date(2026, 5, 4)
    assert "may be granted 3 months" in _notes(r)


# --------------------------------------------------------------------------- #
# Q19 — start event
# --------------------------------------------------------------------------- #


def test_tw_explicit_service_date_is_the_start():
    r = calculate_deadline(_utc(2026, 3, 2), "TW", service_date=date(2026, 3, 10))
    assert r["mailing_date"] == "2026-03-02"
    assert r["start_date"] == "2026-03-10"
    assert r["start_date_basis"] == "service_date"
    assert "MAILING date" not in _notes(r)


def test_tw_without_service_date_falls_back_to_mailing_with_note():
    r = calculate_deadline(_utc(2026, 3, 2), "TW")
    assert r["start_date"] == "2026-03-02"
    assert r["start_date_basis"] == "mailing_date_fallback"
    assert "MAILING date" in _notes(r)


def test_service_date_detected_from_labelled_text():
    text = "發文日期：中華民國115年3月2日\n送達日期：2026-03-09\n申請日：2024-01-01"
    assert extract_service_date(text) == date(2026, 3, 9)
    r = calculate_deadline(_utc(2026, 3, 2), "TW", oa_text=text)
    assert r["start_date"] == "2026-03-09"
    assert r["start_date_basis"] == "service_date"


def test_extract_service_date_never_returns_a_mailing_or_filing_date():
    assert extract_service_date("發文日期：2026-03-02\n申請日：2024-01-01") is None
    assert extract_service_date(None) is None


def test_service_date_before_mailing_is_ignored_with_note():
    r = calculate_deadline(_utc(2026, 3, 2), "TW", service_date=date(2026, 2, 1))
    assert r["start_date"] == "2026-03-02"
    assert "before the mailing date" in _notes(r)


def test_cn_explicit_service_date_overrides_presumption():
    r = calculate_deadline(_utc(2026, 3, 2), "CN", oa_sequence=2, service_date=date(2026, 3, 6))
    assert r["start_date"] == "2026-03-06"
    assert r["start_date_basis"] == "service_date"
    assert "presumed service" not in _notes(r)


@pytest.mark.parametrize("jur", ["US", "EP"])
def test_mailing_based_jurisdictions_have_no_start_note(jur):
    r = calculate_deadline(_utc(2026, 3, 2), jur)
    assert r["start_date_basis"] == "mailing_date"
    assert r["start_date"] == r["mailing_date"] == "2026-03-02"
    assert r["assumptions"] == []


def test_rule_start_events():
    assert {j: r.start_event for j, r in RULES.items()} == {
        "TW": "service",
        "US": "mailing",
        "JP": "mailing",
        "EP": "mailing",
        "CN": "service",
        "KR": "service",
    }
    assert RULES["CN"].presumed_service_days == 15


# --------------------------------------------------------------------------- #
# Q21 — rules_reviewed flag
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("jur", ["TW", "US", "JP", "EP", "CN", "KR", "DE"])
def test_every_result_says_rules_not_reviewed(jur):
    assert calculate_deadline(_utc(2026, 3, 2), jur)["rules_reviewed"] is False


# --------------------------------------------------------------------------- #
# Q20 — calendars
# --------------------------------------------------------------------------- #


def test_tw_2026_revision_has_every_official_day_off():
    h = get_holidays("TW", "2026.2")
    for d in [
        "2026-02-15", "2026-02-20", "2026-02-27", "2026-04-03", "2026-04-06",
        "2026-06-19", "2026-09-25", "2026-09-28", "2026-10-09", "2026-10-26",
        "2026-12-25",
    ]:  # fmt: skip
        assert date.fromisoformat(d) in h, d
    # 2/23 is a working day in 2026 (no 補班; the 春節 block ends 2/22)
    assert date(2026, 2, 23) not in h


def test_auto_prefers_the_highest_revision():
    _h, label, missing = resolve_calendar("TW", "auto", range(2026, 2027))
    assert label == "2026.2" and not missing


def test_old_revision_is_still_version_locked():
    """2026.1 keeps resolving to its own (partial) set — revisions never
    rewrite a published version."""
    assert date(2026, 2, 27) not in get_holidays("TW", "2026.1")


def test_tw_2026_deadline_rolls_off_new_holiday():
    # service 2026-08-09 + 2 months = 2026-10-09 (補假, Fri) -> 10/10 Sat, 10/11 Sun -> Mon 10/12
    r = calculate_deadline(_utc(2026, 8, 9), "TW", service_date=date(2026, 8, 9))
    assert _stat(r) == date(2026, 10, 12)


def test_cn_make_up_working_weekend_does_not_roll():
    """2026-02-28 (Sat) is a 调休 working day: a deadline landing on it stays."""
    assert date(2026, 2, 28) in get_workdays("CN", "2026.1")
    # service 2025-12-28 + 2 months = 2026-02-28
    r = calculate_deadline(_utc(2025, 12, 1), "CN", oa_sequence=2, service_date=date(2025, 12, 28))
    assert _stat(r) == date(2026, 2, 28)
    assert not any("rolled" in w for w in r["warnings"])


def test_cn_ordinary_saturday_still_rolls():
    # service 2026-01-07 + 2 months = 2026-03-07 (ordinary Sat) -> Mon 3/9
    r = calculate_deadline(_utc(2026, 1, 5), "CN", oa_sequence=2, service_date=date(2026, 1, 7))
    assert _stat(r) == date(2026, 3, 9)


def test_cn_spring_festival_2026_block_rolls_to_first_working_day():
    # service 2025-12-17 + 2 months = 2026-02-17 (春节) -> block ends 2/23 -> Tue 2/24
    r = calculate_deadline(_utc(2025, 12, 1), "CN", oa_sequence=2, service_date=date(2025, 12, 17))
    assert _stat(r) == date(2026, 2, 24)


@pytest.mark.parametrize("jur", ["TW", "US", "JP", "EP", "CN", "KR"])
def test_2026_deadlines_are_covered_everywhere(jur):
    r = calculate_deadline(_utc(2026, 3, 2), jur)
    assert not any("does not cover" in w or "⛔ Holiday calendar" in w for w in r["warnings"]), r[
        "warnings"
    ]


@pytest.mark.parametrize("jur", ["TW", "US", "JP", "KR"])
def test_2027_deadlines_are_covered_where_published(jur):
    r = calculate_deadline(_utc(2027, 3, 1), jur)
    assert not any("does not cover" in w for w in r["warnings"]), r["warnings"]


@pytest.mark.parametrize("jur", ["CN", "EP"])
def test_2027_unpublished_calendars_still_warn(jur):
    r = calculate_deadline(_utc(2027, 3, 1), jur)
    assert any("does not cover" in w or "⛔" in w for w in r["warnings"]), r["warnings"]


NEW_FILES = [
    "TW_2026.2", "TW_2027.1", "CN_2026.1", "EP_2026.1",
    "JP_2026.1", "JP_2027.1", "KR_2026.1", "KR_2027.1", "US_2027.1",
]  # fmt: skip


@pytest.mark.parametrize("name", NEW_FILES)
def test_new_calendar_files_cite_sources(name):
    doc = json.loads((CALENDARS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    jur, version = name.split("_")
    assert doc["jurisdiction"] == jur and doc["version"] == version
    assert doc["metadata"]["sources"], name
    assert "verified" in doc["metadata"], name
    for k in doc["holidays"]:
        assert k.startswith(version[:4]), (name, k)


# --------------------------------------------------------------------------- #
# Wire models / endpoint
# --------------------------------------------------------------------------- #


def test_analysis_request_accepts_deadline_fields_and_rejects_bad_dates():
    from backend.shared.models import AnalysisRequest

    base = {"oa_text": "x", "case_id": "C", "target_patent_no": "TW1"}
    ok = AnalysisRequest(**base, applicant_domestic=False, oa_sequence=2, service_date="2026-03-09")
    assert ok.oa_sequence == 2
    with pytest.raises(ValidationError):
        AnalysisRequest(**base, service_date="2026-02-30")
    with pytest.raises(ValidationError):
        AnalysisRequest(**base, oa_sequence=0)


def test_deadline_endpoint_passes_new_fields():
    from fastapi.testclient import TestClient

    from backend.ai_engine.main import app

    with TestClient(app) as c:
        r = c.post(
            "/v1/deadline",
            json={
                "received_date_iso": "2026-03-02T12:00:00+00:00",
                "jurisdiction": "CN",
                "service_date_iso": "2026-03-06",
                "oa_text": "第一次审查意见通知书",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["start_date"] == "2026-03-06"
        assert body["period_applied"].startswith("4 months")
        assert body["rules_reviewed"] is False
        bad = c.post(
            "/v1/deadline",
            json={
                "received_date_iso": "2026-03-02T12:00:00+00:00",
                "service_date_iso": "2026-02-30",
            },
        )
        assert bad.status_code == 422
