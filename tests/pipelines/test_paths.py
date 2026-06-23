# tests/pipelines/test_paths.py
import pytest
from libs.identity.ids import EnterpriseId
from pipelines.data_prep.paths import DatasetPaths

E, U = EnterpriseId("e-0001"), "u-alice"

def test_paths_encode_enterprise_and_user():
    # owner 模型(ADR-024):路径段 = 企业 / 上传用户(非 group)
    p = DatasetPaths(bucket="b", enterprise_id=E, user_id=U, dataset="cc3m")
    assert p.raw_prefix == "e-0001/u-alice/raw/cc3m/"
    assert p.processed_uri == "s3://b/e-0001/u-alice/processed/cc3m.lance"
    assert p.cleaned_prefix == "e-0001/u-alice/cleaned/cc3m/"

def test_dataset_name_validated():
    with pytest.raises(ValueError):
        DatasetPaths(bucket="b", enterprise_id=E, user_id=U, dataset="Bad Name!")
    with pytest.raises(ValueError):
        DatasetPaths(bucket="b", enterprise_id=E, user_id=U, dataset="a/../b")


def _p(dataset="cc3m"):
    return DatasetPaths(bucket="lite-ai", enterprise_id=EnterpriseId("e-0001"),
                        user_id="u-alice", dataset=dataset)

def test_raw_object_key_builds_isolated_path():
    assert _p().raw_object_key("part-0.tar") == "e-0001/u-alice/raw/cc3m/part-0.tar"

@pytest.mark.parametrize("bad", ["../x", "a/b", "/etc/passwd", "..", ".hidden", ""])
def test_raw_object_key_rejects_traversal(bad):
    with pytest.raises(ValueError):
        _p().raw_object_key(bad)
