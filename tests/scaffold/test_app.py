# tests/scaffold/test_app.py
from fastapi.testclient import TestClient
from services._scaffold.app import make_service_app

def test_app_exposes_docs_and_openapi():
    app = make_service_app(title="t-svc", version="0.1.0")
    c = TestClient(app)
    assert c.get("/openapi.json").status_code == 200
    assert c.get("/docs").status_code == 200
    assert c.get("/healthz").json() == {"status": "ok"}

def test_request_id_echoed_in_response_header():
    app = make_service_app(title="t-svc", version="0.1.0")
    c = TestClient(app)
    r = c.get("/healthz", headers={"x-request-id": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"

def test_request_id_generated_when_absent():
    app = make_service_app(title="t-svc", version="0.1.0")
    r = TestClient(app).get("/healthz")
    assert len(r.headers["x-request-id"]) >= 8
