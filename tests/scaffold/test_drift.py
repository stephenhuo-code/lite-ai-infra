# tests/scaffold/test_drift.py
import pytest
from services._scaffold.drift import assert_openapi_subset_of_contract

_CONTRACT = {"paths": {"/v1/me/orgs": {"get": {}}, "/v1/x": {"post": {}}}}

def test_passes_when_runtime_is_subset():
    runtime = {"paths": {"/v1/me/orgs": {"get": {}}}}
    assert_openapi_subset_of_contract(runtime, _CONTRACT)  # 不抛

def test_fails_on_uncontracted_route():
    runtime = {"paths": {"/v1/jobs/{ref}": {"delete": {}}}}  # 契约里没有
    with pytest.raises(AssertionError, match="/v1/jobs"):
        assert_openapi_subset_of_contract(runtime, _CONTRACT)

def test_ignores_builtin_paths():
    runtime = {"paths": {"/docs": {"get": {}}, "/openapi.json": {"get": {}}, "/healthz": {"get": {}}}}
    assert_openapi_subset_of_contract(runtime, _CONTRACT)  # 内建路径豁免
