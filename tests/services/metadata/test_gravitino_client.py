import json
import httpx
import pytest

from services.metadata_service.gravitino import GravitinoClient, GravitinoError


def _c(handler):
    return GravitinoClient(base_url="http://g", transport=httpx.MockTransport(handler))


def test_list_catalogs():
    def h(req):
        assert req.url.path == "/api/metalakes/e_0001/catalogs"
        return httpx.Response(200, json={"identifiers": [{"name": "data"}, {"name": "models"}]})
    assert _c(h).list_catalogs("e_0001") == ["data", "models"]


def test_list_schemas():
    def h(req):
        assert req.url.path == "/api/metalakes/e_0001/catalogs/data/schemas"
        return httpx.Response(200, json={"identifiers": [{"name": "datasets"}]})
    assert _c(h).list_schemas("e_0001", "data") == ["datasets"]


def test_list_filesets():
    def h(req):
        assert req.url.path == "/api/metalakes/e_0001/catalogs/data/schemas/datasets/filesets"
        return httpx.Response(200, json={"identifiers": [{"name": "cc3m"}]})
    assert _c(h).list_filesets("e_0001", "data", "datasets") == ["cc3m"]


def test_get_fileset_exposes_props_location_audit():
    def h(req):
        return httpx.Response(200, json={"fileset": {
            "name": "cc3m", "comment": "desc", "storageLocation": "s3a://b/.../cc3m.lance",
            "properties": {"owner_group": "g-0001", "owner_user": "u-alice", "scope": "private"},
            "audit": {"creator": "svc", "createTime": "2026-06-13T00:00:00Z"}}})
    fs = _c(h).get_fileset("e_0001", "data", "datasets", "cc3m")
    assert fs["properties"]["owner_group"] == "g-0001" and fs["audit"]["creator"] == "svc"


def test_create_fileset_external_with_props():
    seen = {}

    def h(req):
        seen["b"] = json.loads(req.content)
        assert req.url.path == "/api/metalakes/e_0001/catalogs/data/schemas/datasets/filesets"
        return httpx.Response(200, json={"fileset": {"name": "x"}})
    _c(h).create_fileset("e_0001", "data", "datasets", "x", location="s3a://b/x.lance",
                         comment="c", properties={"owner_group": "g-0001", "scope": "private"})
    assert seen["b"]["type"] == "EXTERNAL" and seen["b"]["properties"]["owner_group"] == "g-0001"
    assert seen["b"]["storageLocation"] == "s3a://b/x.lance"


def test_error_raises_gravitino_error():
    def h(req):
        return httpx.Response(404, json={"code": 1003, "type": "NoSuchFilesetException", "message": "nope"})
    with pytest.raises(GravitinoError):
        _c(h).get_fileset("e_0001", "data", "datasets", "nope")


def test_gravitino_error_carries_status():
    def h(req):
        return httpx.Response(404, json={"message": "Fileset does not exist"})
    try:
        _c(h).get_fileset("e_0001", "data", "datasets", "nope")
        assert False, "should raise"
    except GravitinoError as e:
        assert e.status == 404


def test_ensure_metalake_tolerates_conflict():
    def h(req):
        return httpx.Response(409, json={"code": 1004, "type": "MetalakeAlreadyExistsException", "message": "exists"})
    _c(h).ensure_metalake("e_0001")  # 不抛


def test_ensure_metalake_reraises_non_conflict():
    # 非 409(如 404"does not exist")不得被当作冲突吞掉(状态码判定,非字符串)
    def h(req):
        return httpx.Response(404, json={"message": "parent does not exist"})
    with pytest.raises(GravitinoError):
        _c(h).ensure_metalake("e_0001")


def test_ensure_catalog_sends_fileset_and_path_style():
    seen = {}

    def h(req):
        seen["b"] = json.loads(req.content)
        return httpx.Response(200, json={"catalog": {"name": "data"}})
    _c(h).ensure_catalog("e_0001", "data", bucket="lite-ai-dev",
                         s3_endpoint="http://minio:9000", access_key="minio", secret_key="minio123")
    b = seen["b"]
    assert b["type"] == "FILESET"
    assert b["properties"]["s3-path-style-access"] == "true"
    assert b["properties"]["gravitino.bypass.fs.s3a.path.style.access"] == "true"
    assert b["properties"]["filesystem-providers"] == "s3"


def test_ensure_schema_tolerates_conflict():
    def h(req):
        return httpx.Response(409, json={"code": 1004, "type": "SchemaAlreadyExistsException", "message": "exists"})
    _c(h).ensure_schema("e_0001", "data", "datasets")  # 不抛
