from services.gateway.bff.omnigent_proxy import build_forward_headers


def test_inject_identity_and_strip_forged():
    incoming = {"X-Forwarded-Email": "evil@x", "Content-Type": "application/json", "Cookie": "s=1"}
    out = build_forward_headers(incoming, identity_email="alice@acme.test")
    assert out["X-Forwarded-Email"] == "alice@acme.test"   # 我们注入,非客户端
    assert "Cookie" not in out                              # 不外泄会话 cookie 给 omnigent
    assert out["Content-Type"] == "application/json"


def test_case_insensitive_strip_of_forged_header():
    out = build_forward_headers({"x-forwarded-email": "evil@x"}, identity_email="a@b")
    assert out["X-Forwarded-Email"] == "a@b"
    # 客户端的小写伪造头不应残留
    assert all(k.lower() != "x-forwarded-email" or v == "a@b" for k, v in out.items())
