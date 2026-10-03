"""Timeouts must nest: browser > gateway per-call > AI Engine → model.

If the outer wait is shorter than the inner one, the gateway gives up while
the model keeps generating for nobody (and the user's retry queues behind it).
FAILURE_LOG B-13: local mode waited 60 s at the gateway against a 600 s
Ollama budget, so slow drafts were silently replaced by placeholders.
"""

from __future__ import annotations

import pytest

from backend.gateway.orchestrator import ai_call_timeout_sec
from backend.shared.config import settings

# frontend/src/api/client.js LLM_TIMEOUT_MS
SPA_ANALYZE_BUDGET_SEC = 420


@pytest.mark.parametrize(
    "mode, inner",
    [
        ("dify", lambda: settings.DIFY_TIMEOUT_SEC),
        ("local", lambda: settings.OLLAMA_TIMEOUT_SEC),
        ("anthropic", lambda: 2 * settings.LLM_REQUEST_TIMEOUT_SEC),
    ],
)
def test_gateway_wait_outlasts_the_model_budget(monkeypatch, mode, inner):
    monkeypatch.setattr(settings, "LLM_MODE", mode)
    assert ai_call_timeout_sec() > inner()


@pytest.mark.parametrize("mode", ["dify", "local"])
def test_default_on_prem_budgets_fit_inside_the_browser_wait(monkeypatch, mode):
    monkeypatch.setattr(settings, "LLM_MODE", mode)
    monkeypatch.setattr(settings, "DIFY_TIMEOUT_SEC", 300.0)
    monkeypatch.setattr(settings, "OLLAMA_TIMEOUT_SEC", 300)
    assert ai_call_timeout_sec() < SPA_ANALYZE_BUDGET_SEC


@pytest.mark.parametrize(
    "mode, env", [("dify", "DIFY_TIMEOUT_SEC"), ("local", "OLLAMA_TIMEOUT_SEC")]
)
def test_shipped_defaults_fit_inside_the_browser_wait(monkeypatch, mode, env):
    """The test above pins 300 s; this one checks the values that actually
    ship (review: the pinned version passes whatever the default is)."""
    import os

    if os.getenv(env) is not None:
        pytest.skip(f"{env} is overridden in this environment")
    monkeypatch.setattr(settings, "LLM_MODE", mode)
    assert ai_call_timeout_sec() < SPA_ANALYZE_BUDGET_SEC


def test_mock_mode_keeps_a_short_wait(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODE", "mock")
    assert ai_call_timeout_sec() == 60.0
