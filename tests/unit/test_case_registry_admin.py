"""Q27 — case registry admin API (IT_ADMIN only, audited, atomic JSON store)."""

from __future__ import annotations

import json

import pytest

from backend.gateway import audit
from backend.shared import case_registry
from backend.shared.config import settings


@pytest.fixture
def registry(tmp_path, monkeypatch):
    path = tmp_path / "case_registry.json"
    path.write_text(
        json.dumps(
            {
                "_comment": "keep me",
                "cases": {"CASE-A": "public"},
                "patterns": {"CASE-DEMO-*": "public"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CASE_REGISTRY_PATH", str(path))
    return path


def _token(client, user_id):
    r = client.post("/v1/auth/login", json={"user_id": user_id, "password": f"demo-{user_id}"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _last_audit(endpoint):
    rows = [r for r in audit.writer.read_all_rows() if r["endpoint"] == endpoint]
    assert rows, f"no audit row for {endpoint}"
    return rows[-1]


# --- store --------------------------------------------------------------------


def test_create_update_deactivate_roundtrip(registry):
    before, after = case_registry.upsert_case(
        "CASE-NEW", "confidential", actor="carol", note="n", create=True
    )
    assert before is None and after["level"] == "confidential" and after["active"]
    assert case_registry.security_level_for_case("CASE-NEW") == "confidential"

    before, after = case_registry.upsert_case("CASE-NEW", "public", actor="carol", create=False)
    assert before["level"] == "confidential" and after["level"] == "public"
    assert after["note"] == "n"  # note kept when not supplied
    assert case_registry.security_level_for_case("CASE-NEW") == "public"

    before, after = case_registry.deactivate_case("CASE-NEW", actor="carol")
    assert before["active"] and not after["active"]
    assert case_registry.security_level_for_case("CASE-NEW") == "confidential"

    data = json.loads(registry.read_text(encoding="utf-8"))
    assert data["_comment"] == "keep me" and data["patterns"] == {"CASE-DEMO-*": "public"}
    assert data["cases"]["CASE-A"] == "public"  # plain entries preserved


def test_deactivated_case_does_not_fall_through_to_public_pattern(registry):
    case_registry.upsert_case("CASE-DEMO-999", "public", actor="carol", create=True)
    case_registry.deactivate_case("CASE-DEMO-999", actor="carol")
    assert case_registry.security_level_for_case("CASE-DEMO-999") == "confidential"
    assert case_registry.security_level_for_case("CASE-DEMO-001") == "public"


def test_invalid_requests_rejected(registry):
    with pytest.raises(case_registry.RegistryError):
        case_registry.upsert_case("CASE-A", "public", actor="c", create=True)  # duplicate
    with pytest.raises(case_registry.RegistryError):
        case_registry.upsert_case("CASE-X", "public", actor="c", create=False)  # missing
    with pytest.raises(case_registry.RegistryError):
        case_registry.upsert_case("CASE-Y", "secret-ish", actor="c", create=True)  # level
    with pytest.raises(case_registry.RegistryError):
        case_registry.deactivate_case("CASE-X", actor="c")


def test_hand_edit_between_writes_is_merged(registry):
    case_registry.upsert_case("CASE-1", "public", actor="c", create=True)
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["cases"]["CASE-HAND"] = "confidential"
    registry.write_text(json.dumps(data), encoding="utf-8")
    case_registry.upsert_case("CASE-2", "public", actor="c", create=True)
    data = json.loads(registry.read_text(encoding="utf-8"))
    assert {"CASE-1", "CASE-2", "CASE-HAND"} <= set(data["cases"])


# --- API ----------------------------------------------------------------------


@pytest.mark.parametrize("user_id", ["alice", "audit_dave"])
def test_non_admin_is_forbidden_and_audited(gateway_client, registry, user_id):
    tok = _token(gateway_client, user_id)
    r = gateway_client.get("/v1/admin/cases", headers=_h(tok))
    assert r.status_code == 403
    r = gateway_client.post(
        "/v1/admin/cases",
        json={"case_id": "CASE-Z", "security_level": "public"},
        headers=_h(tok),
    )
    assert r.status_code == 403
    row = _last_audit("/v1/admin/cases:create")
    pol = json.loads(row["policy_decisions"])
    assert pol["role_it_admin"] is False and pol["outcome"] == 403
    assert case_registry.get_case("CASE-Z") is None


def test_admin_crud_and_audit_before_after(gateway_client, registry):
    tok = _token(gateway_client, "carol")
    r = gateway_client.get("/v1/admin/cases", headers=_h(tok))
    assert r.status_code == 200
    body = r.json()
    assert {c["case_id"] for c in body["cases"]} == {"CASE-A"}
    assert "public" in body["levels"] and "confidential" in body["levels"]

    r = gateway_client.post(
        "/v1/admin/cases",
        json={"case_id": "CASE-NEW", "security_level": "public", "note": "pilot"},
        headers=_h(tok),
    )
    assert r.status_code == 201, r.text
    pol = json.loads(_last_audit("/v1/admin/cases:create")["policy_decisions"])
    assert pol["registry_level_before"] is None and pol["registry_level_after"] == "public"

    r = gateway_client.put(
        "/v1/admin/cases",
        json={"case_id": "CASE-NEW", "security_level": "confidential"},
        headers=_h(tok),
    )
    assert r.status_code == 200
    row = _last_audit("/v1/admin/cases:update")
    pol = json.loads(row["policy_decisions"])
    assert pol["registry_level_before"] == "public"
    assert pol["registry_level_after"] == "confidential"
    assert row["case_id"] == "CASE-NEW" and row["user_id"] == "carol"

    r = gateway_client.post(
        "/v1/admin/cases/deactivate", json={"case_id": "CASE-NEW"}, headers=_h(tok)
    )
    assert r.status_code == 200 and r.json()["active"] is False
    pol = json.loads(_last_audit("/v1/admin/cases/deactivate")["policy_decisions"])
    assert pol["registry_active_before"] is True and pol["registry_active_after"] is False

    r = gateway_client.post("/v1/admin/cases/lookup", json={"case_id": "CASE-NEW"}, headers=_h(tok))
    assert r.json()["effective_level"] == "confidential"
    r = gateway_client.post(
        "/v1/admin/cases/lookup", json={"case_id": "CASE-DEMO-7"}, headers=_h(tok)
    )
    assert r.json() == {"entry": None, "effective_level": "public"}


def test_admin_bad_level_is_400_and_audited(gateway_client, registry):
    tok = _token(gateway_client, "carol")
    r = gateway_client.post(
        "/v1/admin/cases",
        json={"case_id": "CASE-Q", "security_level": "nope"},
        headers=_h(tok),
    )
    assert r.status_code == 400
    pol = json.loads(_last_audit("/v1/admin/cases:create")["policy_decisions"])
    assert pol["outcome"] == 400


def test_no_delete_endpoint(gateway_client, registry):
    tok = _token(gateway_client, "carol")
    r = gateway_client.request(
        "DELETE", "/v1/admin/cases", json={"case_id": "CASE-A"}, headers=_h(tok)
    )
    assert r.status_code == 405
