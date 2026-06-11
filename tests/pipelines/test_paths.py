# tests/pipelines/test_paths.py
import pytest
from libs.identity.ids import EnterpriseId, GroupId
from pipelines.data_prep.paths import DatasetPaths

E, G = EnterpriseId("e-0001"), GroupId("g-0001")

def test_paths_encode_enterprise_and_group():
    p = DatasetPaths(bucket="b", enterprise_id=E, group_id=G, dataset="cc3m")
    assert p.raw_prefix == "e-0001/g-0001/raw/cc3m/"
    assert p.processed_uri == "s3://b/e-0001/g-0001/processed/cc3m.lance"
    assert p.cleaned_prefix == "e-0001/g-0001/cleaned/cc3m/"

def test_dataset_name_validated():
    with pytest.raises(ValueError):
        DatasetPaths(bucket="b", enterprise_id=E, group_id=G, dataset="Bad Name!")
    with pytest.raises(ValueError):
        DatasetPaths(bucket="b", enterprise_id=E, group_id=G, dataset="a/../b")
