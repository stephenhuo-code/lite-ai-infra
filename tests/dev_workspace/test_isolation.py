from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.identity import context_from_token
from services.dev_workspace_mcp.tools.catalog import read_schema
from services.gateway.bff.wstoken import TokenClaims, WorkspaceTokenStore


class FakeGravitino:
    def __init__(self, fs):
        self._fs = fs

    def get_fileset(self, ml, cat, sch, name):
        return self._fs


_COCO = {"name": "coco", "properties": {"owner_user": "u-alice", "scope": "private",
         "format": "webdataset", "kind": "raw"}, "storageLocation": "s3a://x"}


def _ctx(sub, ent):
    return Context(user=sub, memberships=[Membership(EnterpriseId(ent), "member")])


def test_cross_enterprise_read_denied():
    # 企业 B 的用户读企业 A 的私有数据集 → can() 拒(非本人 owner)→ 不泄露元数据
    out = read_schema(_ctx("u-bob", "ent-other"), FakeGravitino(_COCO), dataset="coco")
    assert out.get("error")
    assert "format" not in out                    # 不回 coco 的任何元数据


def test_forged_token_yields_no_context():
    store = WorkspaceTokenStore()
    assert context_from_token(store, "forged-token") is None   # → 工具 unauthenticated


def test_revoked_session_token_denied():
    store = WorkspaceTokenStore(now=lambda: 0)
    tok = store.mint(TokenClaims("u-alice", "ent-demo", "member", "s1"))
    store.revoke_session("s1")
    assert context_from_token(store, tok) is None
