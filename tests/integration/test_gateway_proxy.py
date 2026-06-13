# tests/integration/test_gateway_proxy.py
import json
import httpx
import pytest
from fastapi.testclient import TestClient
pytestmark = pytest.mark.integration


def test_gateway_to_identity_end_to_end(monkeypatch):
    """gateway 反代 → identity-org 全链路(ASGI 串联,CI 稳定;真两进程见 README 手动验收)。"""
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    from services.identity_org_service.app import app as identity_app
    from services.gateway.app import build_gateway
    transport = httpx.ASGITransport(app=identity_app)
    gw = build_gateway(routes={
        "/v1/me": ("http://id", lambda: httpx.AsyncClient(transport=transport, base_url="http://id")),
    })
    r = TestClient(gw).get("/v1/me/orgs",
                           headers={"x-test-claims": json.dumps({"sub": "u-a", "groups": ["/e-0001/g-0001/members"]})})
    assert r.status_code == 200
    assert r.json()["memberships"][0]["enterprise_id"] == "e-0001"
