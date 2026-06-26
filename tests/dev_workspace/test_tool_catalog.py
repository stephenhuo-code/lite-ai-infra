from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.tools.catalog import read_schema


class FakeGravitino:
    def __init__(self, fs):
        self._fs = fs

    def get_fileset(self, ml, cat, sch, name):
        return self._fs


_OWN = {"name": "coco", "properties": {"owner_user": "u-alice", "scope": "private",
        "format": "webdataset", "num_samples": "5000", "kind": "raw"},
        "storageLocation": "s3a://lite-ai/ent-demo/u-alice/raw/coco/"}


def _ctx(sub, ent="ent-demo"):
    return Context(user=sub, memberships=[Membership(EnterpriseId(ent), "member")])


def test_owner_reads_own_dataset_schema():
    out = read_schema(_ctx("u-alice"), FakeGravitino(_OWN), dataset="coco")
    assert out["format"] == "webdataset" and out["num_samples"] == 5000 and out["owner"] == "u-alice"


def test_non_owner_same_enterprise_denied_private():
    out = read_schema(_ctx("u-eve"), FakeGravitino(_OWN), dataset="coco")
    assert out["error"] == "forbidden"        # can() deny:私有非本人


def test_unattributed_fileset_denied():
    fs = {"name": "x", "properties": {}, "storageLocation": ""}
    out = read_schema(_ctx("u-alice"), FakeGravitino(fs), dataset="x")
    assert out["error"] == "forbidden"        # 不可归属 → fail-closed
