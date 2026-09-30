"""M-14 / ADR-02: a revocation-store outage fails CLOSED with 503 + Retry-After.

A revoked token must never be accepted because the store could not be read,
and a logout must never report success while the token stays live.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.gateway import auth, revocation
from backend.gateway.auth import revoke_token, verify_token
from backend.gateway.revocation import RedisRevocationStore, RevocationUnavailable


class _DownStore:
    def is_revoked(self, jti):
        raise RevocationUnavailable("ConnectionError")

    def revoke(self, jti, ttl_seconds):
        raise RevocationUnavailable("ConnectionError")

    def clear(self):
        pass


def _token():
    return auth.issue_token("alice")


def test_redis_store_wraps_connection_errors():
    pytest.importorskip("redis")
    store = RedisRevocationStore("redis://127.0.0.1:1/0")  # nothing listens here
    with pytest.raises(RevocationUnavailable):
        store.is_revoked("jti")
    with pytest.raises(RevocationUnavailable):
        store.revoke("jti", 60)


def test_verify_token_fails_closed_with_503(monkeypatch):
    token = _token()
    monkeypatch.setattr(revocation, "_store", _DownStore())
    with pytest.raises(HTTPException) as ei:
        verify_token(token)
    assert ei.value.status_code == 503
    assert ei.value.headers["Retry-After"].isdigit()


def test_logout_does_not_claim_success_when_store_is_down(monkeypatch):
    token = _token()
    monkeypatch.setattr(revocation, "_store", _DownStore())
    with pytest.raises(HTTPException) as ei:
        revoke_token(token)
    assert ei.value.status_code == 503
