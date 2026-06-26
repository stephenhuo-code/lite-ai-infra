from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId
from services.dev_workspace_mcp.tools.sample import read_sample


class FakeGravitino:
    def __init__(self, fs):
        self._fs = fs

    def get_fileset(self, *a):
        return self._fs


_FS = {"name": "coco", "properties": {"owner_user": "u-alice", "scope": "private", "format": "webdataset"},
       "storageLocation": "s3a://lite-ai/ent-demo/u-alice/raw/coco/"}


def _ctx(sub):
    return Context(user=sub, memberships=[Membership(EnterpriseId("ent-demo"), "member")])


def test_owner_samples_ok():
    out = read_sample(_ctx("u-alice"), FakeGravitino(_FS), dataset="coco", n=2)
    assert out["dataset"] == "coco" and out["n"] == 2 and "location" in out


def test_non_owner_private_denied():
    out = read_sample(_ctx("u-eve"), FakeGravitino(_FS), dataset="coco", n=2)
    assert out["error"] == "forbidden"
