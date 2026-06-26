from services.gateway.bff.wstoken import WorkspaceTokenStore, TokenClaims


def _store():
    return WorkspaceTokenStore(ttl_seconds=3600, now=lambda: 1000)


def test_mint_then_resolve_roundtrip():
    s = _store()
    tok = s.mint(TokenClaims(sub="u-alice", enterprise="ent-demo", role="member", session="sess-1"))
    assert tok and "ent-demo" not in tok           # 不透明:不泄露身份
    c = s.resolve(tok)
    assert c.sub == "u-alice" and c.enterprise == "ent-demo" and c.role == "member" and c.session == "sess-1"


def test_resolve_unknown_token_returns_none():
    assert _store().resolve("nope") is None


def test_resolve_expired_returns_none():
    s = WorkspaceTokenStore(ttl_seconds=100, now=lambda: 1000)
    tok = s.mint(TokenClaims("u", "ent-demo", "member", "sess-1"))
    s._now = lambda: 1101                            # 过 TTL
    assert s.resolve(tok) is None


def test_revoke_session_invalidates_token():
    s = _store()
    tok = s.mint(TokenClaims("u", "ent-demo", "member", "sess-9"))
    s.revoke_session("sess-9")
    assert s.resolve(tok) is None


from cryptography.fernet import Fernet


def test_two_instances_same_key_interoperate():
    # BFF 铸 / MCP server 解(不同进程=不同实例),同一 key → 跨进程互通(修复 store 不共享 gap)
    key = Fernet.generate_key()
    bff = WorkspaceTokenStore(key=key, now=lambda: 0)
    mcp = WorkspaceTokenStore(key=key, now=lambda: 0)
    tok = bff.mint(TokenClaims(sub="u-alice", enterprise="ent-demo", role="member", session="s1"))
    r = mcp.resolve(tok)
    assert r is not None and r.sub == "u-alice" and r.enterprise == "ent-demo" and r.session == "s1"


def test_different_key_cannot_resolve():
    a = WorkspaceTokenStore(key=Fernet.generate_key(), now=lambda: 0)
    b = WorkspaceTokenStore(key=Fernet.generate_key(), now=lambda: 0)
    tok = a.mint(TokenClaims("u", "ent-demo", "member", "s1"))
    assert b.resolve(tok) is None
