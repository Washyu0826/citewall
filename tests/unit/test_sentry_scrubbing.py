"""Sentry must never carry OA content off the machine (invariants #3 / #7).

send_default_pii=False alone does not stop the Python SDK from shipping frame
locals and the request body (both on by default), so init_sentry() turns those
off and scrub_sentry_event() strips whatever content-bearing fields remain.
"""

from __future__ import annotations

import json
import sys
import types

from backend.shared import observability
from backend.shared.observability import SCRUBBED, scrub_sentry_event

OA_TEXT = "申請人昕澄科技股份有限公司 請求項9「該第一電動車」缺先行詞 alice@example.com"


def _raw_event() -> dict:
    return {
        "level": "error",
        "transaction": "/v1/oa/analyze",
        "request": {
            "method": "POST",
            "url": "http://gw/v1/oa/analyze?case_id=CASE-1",
            "data": {"oa_text": OA_TEXT},
            "query_string": "case_id=CASE-1",
            "headers": {"X-Case-Id": "CASE-1"},
            "cookies": {"session": "x"},
        },
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": f"cannot parse: {OA_TEXT}",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "backend/gateway/orchestrator.py",
                                "function": "orchestrate_analysis",
                                "lineno": 190,
                                "vars": {"req": {"oa_text": OA_TEXT}},
                            }
                        ]
                    },
                }
            ]
        },
        "threads": {
            "values": [{"stacktrace": {"frames": [{"function": "f", "vars": {"t": OA_TEXT}}]}}]
        },
        "logentry": {"message": "draft failed for %s", "params": [OA_TEXT], "formatted": OA_TEXT},
        "message": OA_TEXT,
        "breadcrumbs": {
            "values": [
                {"category": "log", "level": "info", "message": OA_TEXT, "data": {"x": OA_TEXT}}
            ]
        },
        "spans": [
            {"op": "http.client", "description": "POST /v1/parse_oa", "data": {"b": OA_TEXT}}
        ],
        "extra": {"payload": OA_TEXT},
        "user": {"id": "alice", "email": "alice@example.com"},
        "tags": {"env": "test"},
    }


def test_scrub_removes_every_copy_of_oa_text():
    out = scrub_sentry_event(_raw_event())
    dumped = json.dumps(out, ensure_ascii=False)
    assert "昕澄" not in dumped
    assert "該第一電動車" not in dumped
    assert "alice@example.com" not in dumped
    assert "CASE-1" not in dumped  # query string / header / URL query


def test_scrub_keeps_what_is_needed_to_debug():
    out = scrub_sentry_event(_raw_event())
    exc = out["exception"]["values"][0]
    assert exc["type"] == "ValueError"
    assert exc["value"] == SCRUBBED
    frame = exc["stacktrace"]["frames"][0]
    assert (frame["filename"], frame["function"], frame["lineno"]) == (
        "backend/gateway/orchestrator.py",
        "orchestrate_analysis",
        190,
    )
    assert "vars" not in frame
    assert out["request"] == {"method": "POST", "url": "http://gw/v1/oa/analyze"}
    assert out["logentry"] == {"message": "draft failed for %s"}
    assert out["breadcrumbs"]["values"][0] == {"category": "log", "level": "info"}
    assert out["spans"][0] == {"op": "http.client", "description": "POST /v1/parse_oa"}
    assert out["transaction"] == "/v1/oa/analyze"
    assert out["tags"] == {"env": "test"}


def test_scrub_tolerates_minimal_events():
    assert scrub_sentry_event({}) == {}
    assert scrub_sentry_event({"breadcrumbs": [{"message": "m"}]}) == {"breadcrumbs": [{}]}


def test_init_sentry_disables_locals_and_body(monkeypatch):
    captured: dict = {}

    sdk = types.ModuleType("sentry_sdk")
    sdk.init = lambda **kw: captured.update(kw)
    integrations = types.ModuleType("sentry_sdk.integrations")
    fastapi_mod = types.ModuleType("sentry_sdk.integrations.fastapi")
    fastapi_mod.FastApiIntegration = lambda: "fastapi"
    starlette_mod = types.ModuleType("sentry_sdk.integrations.starlette")
    starlette_mod.StarletteIntegration = lambda: "starlette"
    for name, mod in {
        "sentry_sdk": sdk,
        "sentry_sdk.integrations": integrations,
        "sentry_sdk.integrations.fastapi": fastapi_mod,
        "sentry_sdk.integrations.starlette": starlette_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")

    assert observability.init_sentry("gateway") is True
    assert captured["send_default_pii"] is False
    assert captured["include_local_variables"] is False
    assert captured["max_request_body_size"] == "never"

    for hook in ("before_send", "before_send_transaction"):
        out = captured[hook](_raw_event(), {})
        assert "昕澄" not in json.dumps(out, ensure_ascii=False)
        assert out["tags"]["service"] == "gateway"
