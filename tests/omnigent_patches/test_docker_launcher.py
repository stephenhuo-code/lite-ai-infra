"""Regression guard for the omnigent docker SandboxLauncher patch (0004).

The launcher itself lives in the vendored submodule (third_party/omnigent),
which the build cleans + re-applies the patch-queue onto — so it is not
importable from this test tree. Instead we assert the PATCH file exists and
still carries its load-bearing content, so a dropped or silently-degraded
patch (e.g. an upstream bump that reverts our provider registration) fails CI
loudly here rather than surfacing as "unknown sandbox provider 'docker'" at
runtime. The real import/parse correctness is verified in-image by
scripts/omnigent_build.sh (see Task 6 report).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# deploy/omnigent-patches/0004-docker-sandbox-launcher.patch, relative to repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PATCH = _REPO_ROOT / "deploy" / "omnigent-patches" / "0004-docker-sandbox-launcher.patch"


@pytest.fixture(scope="module")
def patch_text() -> str:
    """The 0004 patch contents (fails the suite loud if the patch is gone)."""
    assert _PATCH.is_file(), f"missing patch-queue file: {_PATCH}"
    return _PATCH.read_text(encoding="utf-8")


def test_patch_creates_docker_launcher_module(patch_text: str) -> None:
    """0004 adds the new docker launcher module."""
    assert "diff --git a/omnigent/onboarding/sandboxes/docker.py" in patch_text
    assert "new file mode" in patch_text
    assert "class DockerSandboxLauncher(SandboxLauncher)" in patch_text


def test_patch_launcher_runs_docker_run(patch_text: str) -> None:
    """The launcher provisions via `docker run -d` (the keep-alive container)."""
    # The provision path builds a `docker run -d --name ... --network ...` argv.
    assert '"run",' in patch_text
    assert '"-d",' in patch_text
    assert '"--name",' in patch_text
    assert '"--network",' in patch_text
    # sleep infinity keep-alive entrypoint (exec-model: host started via exec).
    assert "sleep" in patch_text and "infinity" in patch_text


def test_patch_launcher_core_primitives(patch_text: str) -> None:
    """provision / run (docker exec) / put (docker cp) / terminate (docker rm -f)."""
    assert "def provision(self, name: str) -> str" in patch_text
    assert (
        "def run(self, sandbox_id: str, command: str, *, check: bool = True) "
        "-> RemoteCommandResult" in patch_text
    )
    assert "def put(self, sandbox_id: str, local_path: Path, remote_path: str) -> None" in patch_text
    assert "def terminate(self, sandbox_id: str) -> None" in patch_text
    # docker exec / cp / rm -f primitives.
    assert '"exec",' in patch_text
    assert '"cp",' in patch_text
    assert '"rm", "-f"' in patch_text


def test_patch_token_injected_via_env(patch_text: str) -> None:
    """The launch token reaches the host via the OMNIGENT_HOST_TOKEN env.

    The launcher itself injects harness-credential env but NOT the token (the
    base start_host passes the token in the exec env). The guard asserts the
    token env var name is referenced in the patch (docstring / contract), so a
    refactor that drops the token-env contract trips here.
    """
    assert "OMNIGENT_HOST_TOKEN" in patch_text


def test_patch_registers_docker_provider(patch_text: str) -> None:
    """0004 registers `docker` in the launcher registry + server provider sets."""
    # onboarding launcher registry entry.
    assert (
        '"docker": "omnigent.onboarding.sandboxes.docker:DockerSandboxLauncher"' in patch_text
    )
    # server-side provider sets + parse branch.
    assert "SUPPORTED_SANDBOX_PROVIDERS" in patch_text
    assert "PROVIDERS_WITH_MANAGED_LAUNCH" in patch_text
    assert 'provider == "docker"' in patch_text
    assert "_docker_launcher_factory" in patch_text
    assert "DOCKER_MANAGED_TOKEN_TTL_S" in patch_text
