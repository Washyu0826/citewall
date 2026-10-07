#!/usr/bin/env python
"""Smoke-test the public demo container (docker/demo.Dockerfile) from outside.

Runs in CI against `docker compose -f docker-compose.demo.yml up` and works
the same against a deployed Space:

    python scripts/smoke_demo_image.py [BASE_URL]      # default http://127.0.0.1:8080

SMOKE_WAIT_SECONDS (default 180) bounds the wait for the app to come up;
EXPECT_VERSION makes it also wait until /version.txt shows that commit — a
Space keeps serving the OLD build while the new one builds (deploy-demo.yml).

Checks what a visitor gets, through nginx, end to end:
  * the SPA and its security headers (the demo may be framed by
    huggingface.co only; everything else keeps the strict CSP);
  * gzip on the hashed assets;
  * the one-click demo login (published demo password, mock mode only);
  * a browser-supplied identity header is NOT honoured (FAILURE_LOG B-50);
  * /metrics is not open to visitors;
  * a full analysis returns rejections and drafts.
Exit status 1 on the first failed check.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
REPO = Path(__file__).resolve().parent.parent


def request(method, path, body=None, headers=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def check(ok, what):
    print(("OK   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        sys.exit(1)


def header(headers, name):
    return next((v for k, v in headers.items() if k.lower() == name.lower()), "")


# --- up (and the expected build)? -----------------------------------------------
WAIT = int(os.getenv("SMOKE_WAIT_SECONDS", "180"))
EXPECT = os.getenv("EXPECT_VERSION", "").strip()
deadline = time.monotonic() + WAIT
while True:
    try:
        status, _, _ = request("GET", "/api/v1/health", timeout=10)
        live = ""
        if status == 200 and EXPECT:
            vstatus, _, vbody = request("GET", "/version.txt", timeout=10)
            live = vbody.decode("utf-8", "replace").strip() if vstatus == 200 else ""
        if status == 200 and (not EXPECT or live == EXPECT):
            break
    except OSError:
        pass
    if time.monotonic() > deadline:
        check(False, f"app up{' at ' + EXPECT if EXPECT else ''} within {WAIT} s")
    time.sleep(5)
check(True, "gateway health through nginx" + (f" (build {EXPECT})" if EXPECT else ""))

# --- the SPA and its headers ----------------------------------------------------
status, headers, body = request("GET", "/")
html = body.decode("utf-8", "replace")
check(status == 200 and '<div id="root">' in html, "GET / serves the SPA")
csp = header(headers, "Content-Security-Policy")
check("frame-ancestors https://huggingface.co" in csp, "CSP lets huggingface.co (only) frame the demo")
check("unsafe-eval" not in csp and "script-src 'self'" in csp, "script-src stays strict")
check(not header(headers, "X-Frame-Options"), "no X-Frame-Options DENY (it would block the Space page)")

asset = re.search(r'src="(/assets/[^"]+\.js)"', html)
check(asset is not None, "index.html references a hashed JS asset")
status, headers, _ = request("GET", asset.group(1), headers={"Accept-Encoding": "gzip"})
check(status == 200 and header(headers, "Content-Encoding") == "gzip", f"{asset.group(1)} is served gzipped")

# --- login ---------------------------------------------------------------------
status, _, body = request("POST", "/api/v1/auth/login", {"user_id": "alice", "password": "demo-alice"})
check(status == 200, "one-click demo login (published demo password, mock mode)")
token = json.loads(body)["token"]
status, _, _ = request("POST", "/api/v1/auth/login", {"user_id": "alice"})
check(status == 401, "login without any credential is refused")

# --- spoofed identity / metrics -------------------------------------------------
status, _, _ = request(
    "GET",
    "/api/v1/quota",
    headers={"x-user-id": "carol", "x-tenant-id": "tenant_b", "x-user-role": "it_admin"},
)
check(status == 401, "a browser-supplied x-user-id is not an identity (B-50)")
status, _, _ = request("GET", "/api/metrics")
check(status == 401, "/metrics is closed to visitors")

# --- a full analysis -------------------------------------------------------------
oa_text = (REPO / "data" / "oa_samples" / "sample_oa_us.txt").read_text(encoding="utf-8")
status, _, body = request(
    "POST",
    "/api/v1/oa/analyze",
    {"oa_text": oa_text, "case_id": "CASE-2025-001", "target_patent_no": "US17123456"},
    headers={"Authorization": f"Bearer {token}"},
    timeout=180,
)
check(status == 200, f"analyze returns 200 (got {status})")
result = json.loads(body)
check(len(result["oa"]["rejections"]) > 0 and len(result["drafts"]) > 0, "analysis has rejections and drafts")

# --- the demo's smaller hard cap (B-54: masking cost scales with it) ---------------
status, _, _ = request(
    "POST",
    "/api/v1/oa/analyze",
    {"oa_text": "a" * 30_000, "case_id": "CASE-2025-001", "target_patent_no": "US17123456"},
    headers={"Authorization": f"Bearer {token}"},
)
check(status == 413, "a 30k-character OA is over the demo's hard cap (8,000 tokens)")

# --- closed to anonymous visitors (docker/demo/public.conf, B-52) ------------------
for path in ("/api/v1/redact", "/api/v1/audit/append"):
    status, _, _ = request("POST", path, {}, headers={"Authorization": f"Bearer {token}"})
    check(status == 403, f"{path} is closed in the public demo")

# --- a rotating X-Forwarded-For does not get around the login limit ----------------
# Spends the shared login bucket for a minute, so CI only (SMOKE_LOGIN_FLOOD=1),
# never against the live Space. Last, because later logins would fail.
if os.getenv("SMOKE_LOGIN_FLOOD") == "1":
    codes = [
        request(
            "POST",
            "/api/v1/auth/login",
            {"user_id": "alice", "password": "wrong"},
            headers={"X-Forwarded-For": f"203.0.113.{i % 250 + 1}"},
        )[0]
        for i in range(int(os.getenv("LOGIN_RPM", "30")) + 5)
    ]
    check(429 in codes, "a rotating X-Forwarded-For does not reset the login limit (uvicorn --no-proxy-headers)")
print("demo image smoke test passed")
