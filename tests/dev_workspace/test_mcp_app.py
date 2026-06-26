from services.dev_workspace_mcp.app import build_asgi


def test_build_asgi_returns_callable():
    app = build_asgi()
    assert callable(app)
