from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_ws_up_inserts_default_agent_provision_after_omnigent_ready():
    script = Path(__file__).parents[1].parent / "scripts" / "ws_up.sh"
    ws_up = _read(str(script))
    target_command_candidates = [
        'uv run python "$ROOT/scripts/provision_default_agents.py" --enterprise "${EID:-ent-demo}" --omni-base-url "http://127.0.0.1:8900"',
        'uv run python scripts/provision_default_agents.py --enterprise "${EID:-ent-demo}" --omni-base-url "http://127.0.0.1:8900"',
    ]

    command_pos = -1
    chosen_command = None
    for candidate in target_command_candidates:
        candidate_pos = ws_up.find(candidate)
        if candidate_pos >= 0:
            command_pos = candidate_pos
            chosen_command = candidate
            break

    assert command_pos >= 0, "default enterprise agent provision command is missing from ws_up.sh"
    assert 'echo "==> Provision default enterprise agents"' in ws_up
    assert ws_up.find('echo "==> Provision default enterprise agents"') < command_pos

    omnigent_wait = '_wait "omnigent" "http://127.0.0.1:8900/health" \'"ok"\' 120'
    frontend_marker = 'echo "==> [4/5] 前端 build(frontend/dist)+ services up(uvicorn 含 gateway:8090)"'
    assert ws_up.find(omnigent_wait) >= 0, "omnigent readiness wait marker not found"
    assert ws_up.find(frontend_marker) >= 0, "frontend/services phase marker not found"

    omnigent_wait_pos = ws_up.find(omnigent_wait)
    frontend_pos = ws_up.find(frontend_marker)
    assert omnigent_wait_pos < command_pos < frontend_pos, (
        f"expected {chosen_command!r} between omnigent wait and frontend phase"
    )


def test_makefile_has_default_agents_target():
    makefile = _read(str(Path(__file__).parents[1].parent / "Makefile"))
    assert "provision-default-agents" in makefile
    assert "provision-default-agents: ; uv run python scripts/provision_default_agents.py --enterprise $(EID)" in makefile
