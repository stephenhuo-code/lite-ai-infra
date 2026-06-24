from fastapi.testclient import TestClient

from services.metadata_service.app import build_app


class _G:
    def __init__(self):
        self.last = None

    def create_fileset(self, ml, c, s, name, location, comment="", properties=None):
        self.last = {"location": location, "props": properties, "name": name}
        return {"name": name, "storageLocation": location, "properties": properties, "audit": {}}


def _hdr():
    return {"x-test-claims": '{"sub":"u-alice","organization":["e-0001"],"realm_roles":[]}'}


def test_raw_register_pins_location(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    monkeypatch.setenv("DATA_BUCKET", "lite-ai")
    g = _G()
    c = TestClient(build_app(g))
    r = c.post("/v1/catalogs/data/schemas/datasets/datasets",
               json={"name": "coco", "kind": "raw"}, headers=_hdr())
    assert r.status_code == 201, r.text
    # 服务端钉死(owner 路径段=user,ADR-024);Gravitino 边界用 s3a://(HCFS),
    # 校验仍用 s3://(object_store),scheme 二元性。
    assert g.last["location"] == "s3a://lite-ai/e-0001/u-alice/raw/coco/"
    assert g.last["props"]["kind"] == "raw" and g.last["props"]["format"] == "webdataset"
    assert g.last["props"]["owner_user"] == "u-alice" and "owner_group" not in g.last["props"]


def test_processed_register_rejects_foreign_location(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    monkeypatch.setenv("DATA_BUCKET", "lite-ai")
    g = _G()
    c = TestClient(build_app(g))
    r = c.post("/v1/catalogs/data/schemas/datasets/datasets",
               json={"name": "x", "kind": "processed", "format": "lance",
                     "derived_from": "coco",
                     "location": "s3://lite-ai/e-0001/u-bob/processed/x.lance"},  # 别人的 owner 前缀!越权
               headers=_hdr())
    assert r.status_code == 403   # 越权位置被拒(owner 前缀外,ADR-024)


def test_processed_register_accepts_own_location(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    monkeypatch.setenv("DATA_BUCKET", "lite-ai")
    g = _G()
    c = TestClient(build_app(g))
    r = c.post("/v1/catalogs/data/schemas/datasets/datasets",
               json={"name": "coco-clean", "kind": "processed", "format": "lance",
                     "derived_from": "coco",
                     "location": "s3://lite-ai/e-0001/u-alice/processed/coco-clean.lance"},
               headers=_hdr())
    assert r.status_code == 201, r.text
    # 校验用 s3://(caller 自己前缀),转换后 Gravitino location 记 s3a://
    assert g.last["location"] == "s3a://lite-ai/e-0001/u-alice/processed/coco-clean.lance"
    assert g.last["props"]["kind"] == "processed" and g.last["props"]["derived_from"] == "coco"
