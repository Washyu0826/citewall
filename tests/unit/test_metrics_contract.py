"""Metrics contract: what a dashboard charts must be measured, and measurable.

FAILURE_LOG B-17 / B-18: the request-latency histogram topped out at 10 s
while an analysis takes 25–28 s (every sample in +Inf, p95 stuck at 10), and
the citation / prompt-injection / cost / LLM-error metrics were declared and
charted but never written — a dashboard that is green by construction.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.shared import metrics

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
METRICS_PY = BACKEND / "shared" / "metrics.py"


def _registered() -> list[tuple[str, str, str]]:
    """(python name, kind, metric name) for every REGISTRY.register(...) call."""
    src = METRICS_PY.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^(?P<var>[A-Z_][A-Z0-9_]*)\s*=\s*REGISTRY\.register\(\s*(?P<kind>Counter|Histogram|Gauge)\(\s*\"(?P<name>[a-z0-9_]+)\"",
        re.MULTILINE,
    )
    return [(m["var"], m["kind"], m["name"]) for m in pattern.finditer(src)]


def _backend_sources() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in BACKEND.rglob("*.py"))


def test_every_counter_and_histogram_has_a_write_site():
    sources = _backend_sources()
    regs = _registered()
    assert len(regs) >= 10, "metric declarations not found — update the parser"
    missing = []
    for var, kind, name in regs:
        if kind == "Gauge":
            continue  # gauges here are scrape-time bridges (collect=...)
        written = re.search(rf"\b{var}\.(inc|observe)\(", sources) or re.search(
            rf"\b(inc|observe)\(\s*\"{name}\"", sources
        )
        if not written:
            missing.append(name)
    assert not missing, f"declared but never written (a dashboard would read 0): {missing}"


def test_request_latency_buckets_cover_the_analyze_slo():
    buckets = metrics.HTTP_REQUEST_DURATION.buckets
    # SLO thresholds are bucket edges, and the slowest allowed request
    # (nginx 450 s) still lands in a finite bucket.
    for edge in (25.0, 30.0, 90.0, 450.0):
        assert edge in buckets
    assert max(buckets) >= 450.0


def test_a_27_second_analysis_is_not_lost_in_inf():
    h = metrics.Histogram("t_req_seconds", "t", buckets=metrics.REQUEST_LATENCY_BUCKETS)
    h.observe(27.0)
    rendered = "\n".join(h.render())
    assert 't_req_seconds_bucket{le="25"} 0' in rendered
    assert 't_req_seconds_bucket{le="30"} 1' in rendered


def test_health_and_scrape_are_not_timed_as_traffic():
    assert {"/v1/health", "/metrics"} <= metrics.UNTIMED_PATHS


def test_a_degraded_fallback_counts_as_an_llm_error():
    before = dict(metrics.LLM_ERRORS._snapshot())
    metrics.record_llm_usage({"model_used": "qwen2.5:7b-DEGRADED-mock"})
    after = dict(metrics.LLM_ERRORS._snapshot())
    assert sum(after.values()) == sum(before.values()) + 1
