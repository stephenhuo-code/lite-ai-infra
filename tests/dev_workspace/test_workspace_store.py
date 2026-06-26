import pytest

from services.gateway.bff.workspace_store import workspace_prefix


def test_prefix_is_enterprise_owner_workspace_scoped():
    assert workspace_prefix(enterprise="ent-demo", owner="u-alice", ws="coco-clean") \
        == "ent-demo/u-alice/workspace/coco-clean/"


def test_prefix_rejects_traversal():
    with pytest.raises(ValueError):
        workspace_prefix(enterprise="ent-demo", owner="u-alice", ws="../escape")


from services.gateway.bff.workspace_store import hydrate, persist


class FakeOSS:
    def __init__(self, objs):
        self.objs = dict(objs)

    def list(self, prefix):
        return [k for k in self.objs if k.startswith(prefix)]

    def get(self, k):
        return self.objs[k]

    def put_object(self, k, b):
        self.objs[k] = b


class FakeFS:
    def __init__(self):
        self.files = {}

    def write(self, rel, b):
        self.files[rel] = b

    def read(self, rel):
        return self.files[rel]

    def listrel(self):
        return list(self.files)


def test_hydrate_copies_oss_to_fs():
    oss = FakeOSS({"ent-demo/u-alice/workspace/w/recipe.py": b"x"})
    fs = FakeFS()
    n = hydrate(oss, fs, prefix="ent-demo/u-alice/workspace/w/")
    assert n == 1 and fs.files["recipe.py"] == b"x"


def test_persist_copies_fs_to_oss_under_prefix():
    oss = FakeOSS({})
    fs = FakeFS()
    fs.write("recipe.py", b"y")
    persist(oss, fs, prefix="ent-demo/u-alice/workspace/w/")
    assert "ent-demo/u-alice/workspace/w/recipe.py" in oss.objs
