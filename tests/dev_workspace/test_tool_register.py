from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.tools.register import register_processed


class FakeMeta:
    def __init__(self):
        self.created = None

    def create(self, **kw):
        self.created = kw
        return {"name": kw["name"], "owner": kw["owner"]}


def _ctx(sub="u-alice"):
    return Context(user=sub, memberships=[Membership(EnterpriseId("ent-demo"), "member")])


def test_register_within_owner_prefix_ok():
    meta = FakeMeta()
    out = register_processed(_ctx(), meta, name="coco-clean",
                             location="s3://lite-ai/ent-demo/u-alice/processed/coco-clean.lance",
                             derived_from="coco")
    assert out["owner"] == "u-alice" and meta.created["name"] == "coco-clean"


def test_register_outside_prefix_denied():
    meta = FakeMeta()
    out = register_processed(_ctx(), meta, name="x",
                             location="s3://lite-ai/ent-other/u-eve/processed/x.lance", derived_from="coco")
    assert out["error"] == "forbidden" and meta.created is None
