# tests/gateway/bff/test_session.py —— Task 3:Fernet 加密会话 codec(纯逻辑 TDD)
from cryptography.fernet import Fernet
from services.gateway.bff.session import SessionCodec, SessionData


def _codec():
    return SessionCodec(Fernet.generate_key())


def test_roundtrip():
    c = _codec()
    s = SessionData(access_token="a", refresh_token="r", expires_at=1900000000)
    got = c.decode(c.encode(s))
    assert got.access_token == "a" and got.refresh_token == "r" and got.expires_at == 1900000000


def test_roundtrip_preserves_csrf():
    c = _codec()
    s = SessionData(access_token="a", refresh_token="r", expires_at=1900000000, csrf="tok-123")
    assert c.decode(c.encode(s)).csrf == "tok-123"


def test_tampered_cookie_returns_none():
    assert _codec().decode("not-a-valid-token") is None


def test_wrong_key_returns_none():
    # 另一把 key 加密的 cookie 不得被本 codec 解出(密钥轮换/伪造 → None)
    other = SessionCodec(Fernet.generate_key())
    token = other.encode(SessionData("a", "r", 1900000000))
    assert _codec().decode(token) is None


def test_is_expired():
    assert SessionData("a", "r", 0).is_expired(now=100) is True
    assert SessionData("a", "r", 1000).is_expired(now=100) is False


def test_is_expired_skew():
    # skew 内即视为过期(默认 30s 提前刷新窗口)
    assert SessionData("a", "r", 120).is_expired(now=100) is True   # 100 >= 120-30
    assert SessionData("a", "r", 200).is_expired(now=100) is False  # 100 < 200-30
