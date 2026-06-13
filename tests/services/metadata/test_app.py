import json
import pathlib

import pytest
import yaml
from fastapi.testclient import TestClient

from services._scaffold.drift import assert_openapi_subset_of_contract


@pytest.fixture(autouse=True)
def _seam(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")


class FakeG:
    def __init__(self):
        self._fs = {
            "cc3m": {"name": "cc3m", "comment": "c",
                     "storageLocation": "s3a://b/e-0001/g-0001/processed/cc3m.lance",
                     "properties": {"owner_group": "g-0001", "owner_user": "u-alice", "scope": "private"},
                     "audit": {"creator": "u-alice", "createTime": "2026-06-13T00:00:00Z"}},
            "secret": {"name": "secret", "comment": "",
                       "storageLocation": "s3a://b/e-0001/g-0002/processed/secret.lance",
                       "properties": {"owner_group": "g-0002", "owner_user": "u-bob", "scope": "private"},
                       "audit": {"creator": "u-bob", "createTime": "2026-06-13T00:00:00Z"}}}

    def list_catalogs(self, ml):
        return ["data"]

    def list_schemas(self, ml, cat):
        return ["datasets"]

    def list_filesets(self, ml, cat, sch):
        return list(self._fs)

    def get_fileset(self, ml, cat, sch, name):
        if name not in self._fs:
            raise KeyError(name)
        return self._fs[name]

    def create_fileset(self, ml, cat, sch, name, location, comment="", properties=None):
        self._fs[name] = {"name": name, "comment": comment, "storageLocation": location,
                          "properties": properties,
                          "audit": {"creator": properties["owner_user"], "createTime": "t"}}
        return self._fs[name]


def _client(g=None):
    from services.metadata_service.app import build_app
    return TestClient(build_app(gravitino=g or FakeG()))


def _h(sub, groups):
    return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}


_ALICE = _h("u-alice", ["/e-0001/g-0001/members"])
_DS = "/v1/catalogs/data/schemas/datasets/datasets"


def test_list_catalogs_enterprise_level():
    r = _client().get("/v1/catalogs", headers=_ALICE)
    assert r.status_code == 200 and r.json()["names"] == ["data"]


def test_list_schemas():
    r = _client().get("/v1/catalogs/data/schemas", headers=_ALICE)
    assert r.status_code == 200 and r.json()["names"] == ["datasets"]


def test_list_datasets_can_filtered_to_own_group():
    r = _client().get(_DS, headers=_ALICE)
    assert [d["name"] for d in r.json()["datasets"]] == ["cc3m"]  # secret(g-0002) 被过滤


def test_dataset_projection_has_audit_and_comment():
    d = _client().get(f"{_DS}/cc3m", headers=_ALICE).json()
    assert d == {"name": "cc3m", "enterprise_id": "e-0001", "group_id": "g-0001", "owner": "u-alice",
                 "scope": "private", "location": "s3a://b/e-0001/g-0001/processed/cc3m.lance",
                 "comment": "c", "created_at": "2026-06-13T00:00:00Z", "created_by": "u-alice"}


def test_get_cross_group_403():
    assert _client().get(f"{_DS}/secret", headers=_ALICE).status_code == 403


def test_get_missing_404():
    assert _client().get(f"{_DS}/nope", headers=_ALICE).status_code == 404


def test_unattributed_fileset_fail_closed_not_500():
    # 缺 owner_group 的带外/未治理 fileset:PEP 必须 fail-closed(deny/不列出),绝不崩成 500
    g = FakeG()
    g._fs["orphan"] = {"name": "orphan", "comment": "", "storageLocation": "s3a://b/x.lance",
                       "properties": {"scope": "private"}, "audit": {}}     # 无 owner_group
    c = _client(g)
    # get → 403(非 500)
    assert c.get(f"{_DS}/orphan", headers=_ALICE).status_code == 403
    # list → 不抛、不含 orphan(只剩可归属且 can() 允许的 cc3m)
    r = c.get(_DS, headers=_ALICE)
    assert r.status_code == 200 and "orphan" not in [d["name"] for d in r.json()["datasets"]]


def test_register_own_group_201():
    g = FakeG()
    r = _client(g).post(_DS, headers=_ALICE, json={"name": "newds", "group_id": "g-0001",
                                                   "location": "s3a://b/e-0001/g-0001/processed/newds.lance"})
    assert r.status_code == 201 and "newds" in g._fs


def test_register_other_group_403():
    assert _client().post(_DS, headers=_ALICE, json={"name": "x", "group_id": "g-0002",
                                                     "location": "s3a://b/x.lance"}).status_code == 403


def test_register_missing_field_422():
    # 契约模型校验:缺 group_id/location → 422(不是 500)
    r = _client().post(_DS, headers=_ALICE, json={"name": "x"})
    assert r.status_code == 422


def test_register_invalid_name_422():
    # name 违反契约 pattern → 422
    r = _client().post(_DS, headers=_ALICE,
                       json={"name": "Bad Name!", "group_id": "g-0001", "location": "s3a://b/x.lance"})
    assert r.status_code == 422


def test_ambiguous_enterprise_400():
    # v1 单企业:同时属多个企业 → 拒绝(不静默挑第一个,宪法 §3.7)
    h = _h("u-multi", ["/e-0001/g-0001/members", "/e-0002/g-0002/members"])
    assert _client().get("/v1/catalogs", headers=h).status_code == 400


def test_unauth_401(monkeypatch):
    monkeypatch.delenv("LITEAI_ALLOW_TEST_CLAIMS", raising=False)
    assert _client().get("/v1/catalogs").status_code == 401


def test_docs_and_contract():
    c = _client()
    assert c.get("/docs").status_code == 200
    contract = yaml.safe_load(pathlib.Path("contracts/openapi/metadata.yaml").read_text())
    assert_openapi_subset_of_contract(c.app.openapi(), contract)
