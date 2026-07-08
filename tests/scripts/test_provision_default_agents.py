import os
import subprocess
import sys
import tempfile

from scripts import provision_default_agents as p


class _Result:
    created = ["minimax", "debby"]
    skipped = ["codex", "polly"]


def test_main_calls_seed_with_enterprise(monkeypatch, capsys):
    seen = {}
    audit = object()

    def fake_seed(alias, *, omni_base_url, identity_email, transport=None, audit_writer=None):
        seen["alias"] = alias
        seen["base"] = omni_base_url
        seen["email"] = identity_email
        seen["audit_writer"] = audit_writer
        return _Result()

    monkeypatch.setattr(p, "_default_audit_writer", lambda: audit)
    monkeypatch.setattr(p, "ensure_default_agents_for_enterprise", fake_seed)
    rc = p.main(["--enterprise", "ent-demo", "--omni-base-url", "http://omni"])

    assert rc == 0
    assert seen == {
        "alias": "ent-demo",
        "base": "http://omni",
        "email": "system@lite-ai.local",
        "audit_writer": audit,
    }
    out = capsys.readouterr().out
    assert "created: minimax, debby" in out
    assert "skipped: codex, polly" in out


def test_script_help_runs_as_direct_cli():
    env = os.environ.copy()
    # 用可移植的临时目录做 uv cache(此前硬编 /private/tmp/uv-cache 是 macOS 专有路径,
    # Linux CI 上 Permission denied → 让整条 CI 变红)。
    env["UV_CACHE_DIR"] = tempfile.mkdtemp(prefix="uv-cache-")

    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/provision_default_agents.py",
            "--help",
        ],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Provision default enterprise agents" in result.stdout
