import pathlib
from fastapi.testclient import TestClient
from services.gateway.static import install_static

def _app(tmp_path, monkeypatch):
    from fastapi import FastAPI
    dist = tmp_path / "dist"; (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    (dist / "assets" / "x.js").write_text("console.log(1)")
    app = FastAPI()
    @app.get("/auth/me")
    def me(): return {"user": "u"}
    @app.get("/v1/ping")
    def ping(): return {"ok": True}
    install_static(app, dist_dir=str(dist))
    return TestClient(app)

def test_unknown_route_returns_index_html(tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch)
    r = c.get("/datasets")
    assert r.status_code == 200 and "<title>app</title>" in r.text

def test_api_routes_not_swallowed(tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch)
    assert c.get("/auth/me").json() == {"user": "u"}
    assert c.get("/v1/ping").json() == {"ok": True}

def test_asset_served(tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch)
    assert c.get("/assets/x.js").status_code == 200
