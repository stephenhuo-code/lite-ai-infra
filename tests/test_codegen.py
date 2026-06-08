# tests/test_codegen.py
import importlib, subprocess

def test_codegen_produces_importable_models():
    subprocess.run(["make", "gen"], check=True)
    m = importlib.import_module("libs.contracts_gen.identity_org_models")
    assert hasattr(m, "Membership") and hasattr(m, "Memberships")
