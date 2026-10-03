"""Numbers the docs state must match the code that defines them.

Three times a fix changed a value and the documentation kept the old one
(FAILURE_LOG D-1, D-3, D-4: the request-id cap stayed "200" after B-22 made it
128). These checks make the next drift a test failure instead of a reader's
wrong assumption.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.gateway import main as gw_main
from backend.shared import observability

REPO = Path(__file__).resolve().parents[2]
README = (REPO / "docs" / "observability" / "README.md").read_text(encoding="utf-8")
CONFIG = (REPO / "backend" / "shared" / "config.py").read_text(encoding="utf-8")
ENV_EXAMPLE = (REPO / ".env.example").read_text(encoding="utf-8")
CLIENT_JS = (REPO / "frontend" / "src" / "api" / "client.js").read_text(encoding="utf-8")


def _config_default(name: str) -> str:
    match = re.search(rf'{name}", "([^"]+)"', CONFIG)
    assert match, f"{name} default not found in config.py"
    return match.group(1)


def test_the_documented_request_id_cap_is_the_code_s():
    assert f"length-capped at {observability._MAX_REQUEST_ID_LEN}" in README


def test_the_analysis_deadline_default_is_the_same_everywhere():
    default = _config_default("ANALYZE_DEADLINE_SEC")
    assert f"ANALYZE_DEADLINE_SEC={default}" in ENV_EXAMPLE
    assert f"`ANALYZE_DEADLINE_SEC`, default {default} s" in README


def test_the_analysis_deadline_fits_inside_the_spa_budget():
    spa_ms = int(re.search(r"LLM_TIMEOUT_MS = ([\d_]+);", CLIENT_JS).group(1).replace("_", ""))
    assert gw_main._SPA_ANALYZE_BUDGET_SEC * 1000 == spa_ms
    assert float(_config_default("ANALYZE_DEADLINE_SEC")) < spa_ms / 1000


def test_the_redis_timeout_default_is_documented():
    default = _config_default("REDIS_SOCKET_TIMEOUT_SEC")
    assert f"REDIS_SOCKET_TIMEOUT_SEC={default}" in ENV_EXAMPLE
