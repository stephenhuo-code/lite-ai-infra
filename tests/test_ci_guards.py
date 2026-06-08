# tests/test_ci_guards.py
import subprocess

def test_guards_pass_on_clean_tree():
    r = subprocess.run(["bash", "scripts/ci_guards.sh"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
