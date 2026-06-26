from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.tools.oss import allowed_prefix, oss_read


class FakeOSS:
    def __init__(self, blob=b"hi"):
        self.blob = blob
        self.got = None

    def get(self, path):
        self.got = path
        return self.blob


def _ctx(sub="u-alice", ent="ent-demo"):
    return Context(user=sub, memberships=[Membership(EnterpriseId(ent), "member")])


def test_allowed_prefix_is_enterprise_owner_scoped():
    assert allowed_prefix(_ctx()) == "ent-demo/u-alice/"


def test_oss_read_within_prefix_ok():
    oss = FakeOSS(b"data")
    out = oss_read(_ctx(), oss, path="ent-demo/u-alice/raw/coco/0.tar")
    assert out["bytes_len"] == 4 and oss.got.endswith("0.tar")


def test_oss_read_outside_prefix_denied():
    oss = FakeOSS()
    out = oss_read(_ctx(), oss, path="ent-other/u-eve/secret")
    assert out == {"error": "forbidden"} and oss.got is None   # 未触达存储
