# tests/services/identity_org/test_me_orgs.py
import json, os, pathlib
import pytest
import yaml
from fastapi.testclient import TestClient
from services._scaffold.drift import assert_openapi_subset_of_contract


@pytest.fixture(autouse=True)
def _seam(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")


def _client():
    from services.identity_org_service.app import app
    return TestClient(app)


def _hdr(sub, organization, realm_roles=()):
    return {"x-test-claims": json.dumps(
        {"sub": sub, "organization": list(organization), "realm_roles": list(realm_roles)})}


def test_me_orgs_contract_shape():
    r = _client().get("/v1/me/orgs", headers=_hdr("u-alice", ["e-0001"]))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"user", "is_platform_admin", "memberships"}
    # 身份降两级:投影只含 enterprise_id/role(无 group_id)
    assert body["memberships"][0] == {"enterprise_id": "e-0001", "role": "member"}


def test_me_orgs_unauthenticated_401(monkeypatch):
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    assert _client().get("/v1/me/orgs").status_code == 401


def test_docs_available():
    assert _client().get("/docs").status_code == 200


def test_runtime_matches_contract():
    contract = yaml.safe_load(pathlib.Path("contracts/openapi/identity-org.yaml").read_text())
    runtime = _client().app.openapi()
    assert_openapi_subset_of_contract(runtime, contract)
