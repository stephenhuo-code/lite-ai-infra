import yaml, pathlib
from fastapi.testclient import TestClient
from libs.audit.oss_audit import AuditWriter
from services._scaffold.drift import assert_openapi_subset_of_contract
from services.data_pipeline_service.app import build_app
from services.data_pipeline_service.jobs import JobStore
from services.data_pipeline_service.scheduler import SubprocessJobRunner

def test_runtime_matches_contract(tmp_path):
    class _S:
        def put(self, k, b): ...
    app = build_app(SubprocessJobRunner(JobStore(str(tmp_path)), spawn=lambda *a, **k: None), AuditWriter(_S()))
    contract = yaml.safe_load(pathlib.Path("contracts/openapi/data-pipeline.yaml").read_text())
    assert_openapi_subset_of_contract(TestClient(app).app.openapi(), contract)
