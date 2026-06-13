# tests/scripts/test_swagger_urls.py
import importlib.util, pathlib

_spec = importlib.util.spec_from_file_location(
    "swagger_urls", pathlib.Path("scripts/swagger_urls.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_discovers_contracts(tmp_path):
    (tmp_path / "identity-org.yaml").write_text("openapi: 3.1.0")
    (tmp_path / "metadata.yaml").write_text("openapi: 3.1.0")
    urls = _mod.build_urls(str(tmp_path))
    assert urls == [
        {"url": "/contracts/identity-org.yaml", "name": "identity-org"},
        {"url": "/contracts/metadata.yaml", "name": "metadata"},
    ]


def test_real_contracts_dir_includes_identity_org():
    names = [u["name"] for u in _mod.build_urls()]
    assert "identity-org" in names
