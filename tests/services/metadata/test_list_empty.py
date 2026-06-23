from fastapi.testclient import TestClient

from services.metadata_service.app import build_app
from services.metadata_service.gravitino import GravitinoError


class _G:
    def list_filesets(self, ml, c, s):
        raise GravitinoError("404 NoSuchSchema", status=404)


def test_list_empty_on_missing_catalog(monkeypatch):
    monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")
    c = TestClient(build_app(_G()))
    r = c.get("/v1/catalogs/data/schemas/datasets/datasets",
              headers={"x-test-claims": '{"sub":"u-alice","groups":["/e-0001/g-0001/members"]}'})
    assert r.status_code == 200 and r.json() == {"datasets": []}
