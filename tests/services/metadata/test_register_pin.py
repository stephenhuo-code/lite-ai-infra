from fastapi.testclient import TestClient

from services.metadata_service.app import build_app


class _G:
    def __init__(self):
        self.last = None

    def create_fileset(self, ml, c, s, name, location, comment="", properties=None):
        self.last = {"location": location, "props": properties, "name": name}
        return {"name": name, "storageLocation": location, "properties": properties, "audit": {}}


def _hdr():
    return {"x-test-claims": '{"sub":"u-alice","groups":["/e-0001/g-0001/members"]}'}


def test_raw_register_pins_location(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    monkeypatch.setenv("DATA_BUCKET", "lite-ai")
    g = _G()
    c = TestClient(build_app(g))
    r = c.post("/v1/catalogs/data/schemas/datasets/datasets",
               json={"name": "coco", "group_id": "g-0001", "kind": "raw"}, headers=_hdr())
    assert r.status_code == 201, r.text
    assert g.last["location"] == "s3://lite-ai/e-0001/g-0001/raw/coco/"     # 服务端钉死
    assert g.last["props"]["kind"] == "raw" and g.last["props"]["format"] == "webdataset"


def test_processed_register_rejects_foreign_location(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    monkeypatch.setenv("DATA_BUCKET", "lite-ai")
    g = _G()
    c = TestClient(build_app(g))
    r = c.post("/v1/catalogs/data/schemas/datasets/datasets",
               json={"name": "x", "group_id": "g-0001", "kind": "processed", "format": "lance",
                     "derived_from": "coco",
                     "location": "s3://lite-ai/e-0001/g-0002/processed/x.lance"},  # 别组!越权
               headers=_hdr())
    assert r.status_code == 403   # 越权位置被拒


def test_processed_register_accepts_own_location(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    monkeypatch.setenv("DATA_BUCKET", "lite-ai")
    g = _G()
    c = TestClient(build_app(g))
    r = c.post("/v1/catalogs/data/schemas/datasets/datasets",
               json={"name": "coco-clean", "group_id": "g-0001", "kind": "processed", "format": "lance",
                     "derived_from": "coco",
                     "location": "s3://lite-ai/e-0001/g-0001/processed/coco-clean.lance"},
               headers=_hdr())
    assert r.status_code == 201, r.text
    assert g.last["props"]["kind"] == "processed" and g.last["props"]["derived_from"] == "coco"
