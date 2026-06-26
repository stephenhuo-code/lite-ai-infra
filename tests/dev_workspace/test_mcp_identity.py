from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.identity import (
    context_from_token,
    current_context,
    set_current_token,
)
from services.gateway.bff.wstoken import TokenClaims, WorkspaceTokenStore


def test_token_resolves_to_context_with_owner_and_enterprise():
    store = WorkspaceTokenStore(now=lambda: 0)
    tok = store.mint(TokenClaims(sub="u-alice", enterprise="ent-demo", role="member", session="s1"))
    ctx = context_from_token(store, tok)
    assert ctx.user == "u-alice"
    assert ctx.role_in(EnterpriseId("ent-demo")) == "member"


def test_unknown_token_yields_none():
    store = WorkspaceTokenStore()
    assert context_from_token(store, "bad") is None


def test_current_context_uses_contextvar():
    store = WorkspaceTokenStore(now=lambda: 0)
    tok = store.mint(TokenClaims("u-bob", "ent-demo", "enterprise-admin", "s2"))
    set_current_token(store, tok)
    assert current_context().user == "u-bob"
