import os
import textwrap
import pytest
from libs.config import load_settings, ConfigError, export_env, SERVICE_ENV_KEYS

def _write(tmp_path, name, body):
    d = tmp_path / "configs"; d.mkdir(exist_ok=True)
    (d / name).write_text(textwrap.dedent(body)); return tmp_path

def test_load_local_resolves_literal_values(tmp_path):
    root = _write(tmp_path, "local.yaml", """
        env: local
        oss: {endpoint: 'http://localhost:9000', access_key: minio, secret_key: minio123,
              region: us-east-1, data_bucket: lite-ai, audit_bucket: lite-ai}
        auth: {jwks_url: 'http://localhost:8080/x'}
        services: {identity_url: 'http://localhost:8001', metadata_url: 'http://localhost:8002',
                   data_pipeline_url: 'http://localhost:8003', gateway_url: 'http://localhost:8090'}
        bff: {session_key: devkey, redirect_uri: 'http://localhost:8090/auth/callback',
              oidc_client_id: lite-ai-web, oidc_client_secret: dev-web-secret,
              oidc_issuer: 'http://localhost:8080/realms/lite-ai'}
        gravitino: {url: 'http://localhost:8091'}
        pipeline: {jobs_dir: ./.dev/jobs, dj_bin: ./.dj-venv/bin/dj-process}
    """)
    s = load_settings("local", root=root)
    assert s.oss.endpoint == "http://localhost:9000"
    assert s.oss.access_key == "minio"

def test_test_env_missing_secret_fails_fast(tmp_path, monkeypatch):
    monkeypatch.delenv("OSS_SECRET_KEY", raising=False)
    root = _write(tmp_path, "test.yaml", """
        env: test
        oss: {endpoint: 'https://oss-cn-hangzhou.aliyuncs.com', access_key: '${OSS_ACCESS_KEY}',
              secret_key: '${OSS_SECRET_KEY}', region: cn-hangzhou, data_bucket: t, audit_bucket: t}
        auth: {jwks_url: 'https://x/certs'}
        services: {identity_url: 'http://i', metadata_url: 'http://m',
                   data_pipeline_url: 'http://d', gateway_url: 'http://g'}
        bff: {session_key: '${BFF_SESSION_KEY}', redirect_uri: 'http://g/auth/callback',
              oidc_client_id: w, oidc_client_secret: '${OIDC_CLIENT_SECRET}', oidc_issuer: 'http://x'}
        gravitino: {url: 'http://grav'}
        pipeline: {jobs_dir: /var/jobs, dj_bin: /usr/bin/dj-process}
    """)
    with pytest.raises(ConfigError) as ei:
        load_settings("test", root=root)
    assert "OSS_SECRET_KEY" in str(ei.value)

def test_test_env_with_secret_injected_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("OSS_ACCESS_KEY", "AK"); monkeypatch.setenv("OSS_SECRET_KEY", "SK")
    monkeypatch.setenv("BFF_SESSION_KEY", "BK"); monkeypatch.setenv("OIDC_CLIENT_SECRET", "CS")
    root = _write(tmp_path, "test.yaml", """
        env: test
        oss: {endpoint: 'https://oss-cn-hangzhou.aliyuncs.com', access_key: '${OSS_ACCESS_KEY}',
              secret_key: '${OSS_SECRET_KEY}', region: cn-hangzhou, data_bucket: t, audit_bucket: t}
        auth: {jwks_url: 'https://x/certs'}
        services: {identity_url: 'http://i', metadata_url: 'http://m',
                   data_pipeline_url: 'http://d', gateway_url: 'http://g'}
        bff: {session_key: '${BFF_SESSION_KEY}', redirect_uri: 'http://g/auth/callback',
              oidc_client_id: w, oidc_client_secret: '${OIDC_CLIENT_SECRET}', oidc_issuer: 'http://x'}
        gravitino: {url: 'http://grav'}
        pipeline: {jobs_dir: /var/jobs, dj_bin: /usr/bin/dj-process}
    """)
    s = load_settings("test", root=root)
    assert s.oss.secret_key == "SK"

def test_local_env_with_unfilled_placeholder_is_error(tmp_path):
    # local 档不该有占位:出现 ${VAR} 即配置写错
    root = _write(tmp_path, "local.yaml", """
        env: local
        oss: {endpoint: 'http://localhost:9000', access_key: minio, secret_key: '${OSS_SECRET_KEY}',
              region: us-east-1, data_bucket: lite-ai, audit_bucket: lite-ai}
        auth: {jwks_url: 'http://x'}
        services: {identity_url: 'http://i', metadata_url: 'http://m',
                   data_pipeline_url: 'http://d', gateway_url: 'http://g'}
        bff: {session_key: k, redirect_uri: 'http://g/cb', oidc_client_id: w,
              oidc_client_secret: s, oidc_issuer: 'http://x'}
        gravitino: {url: 'http://grav'}
        pipeline: {jobs_dir: ./.dev/jobs, dj_bin: ./x}
    """)
    with pytest.raises(ConfigError):
        load_settings("local", root=root)

def test_repo_local_yaml_loads():
    # 仓库真 configs/local.yaml 必须能在无任何 env 注入下解析(本地不依赖密钥)
    s = load_settings("local")
    assert s.oss.endpoint == "http://localhost:9000"
    assert s.gravitino.url == "http://localhost:8091"
    assert "aliyuncs" not in s.oss.endpoint   # local 绝不指云(SC-001)

def test_missing_section_raises_config_error_not_typeerror(tmp_path):
    # 整段缺失(无 services:)应抛 ConfigError,而非裸 TypeError
    root = _write(tmp_path, "local.yaml", """
        env: local
        oss: {endpoint: 'http://localhost:9000', access_key: minio, secret_key: minio123,
              region: us-east-1, data_bucket: lite-ai, audit_bucket: lite-ai}
        auth: {jwks_url: 'http://localhost:8080/x'}
        bff: {session_key: devkey, redirect_uri: 'http://localhost:8090/auth/callback',
              oidc_client_id: lite-ai-web, oidc_client_secret: dev-web-secret,
              oidc_issuer: 'http://localhost:8080/realms/lite-ai'}
        gravitino: {url: 'http://localhost:8091'}
        pipeline: {jobs_dir: ./.dev/jobs, dj_bin: ./.dj-venv/bin/dj-process}
    """)
    with pytest.raises(ConfigError):
        load_settings("local", root=root)

_BASELINE = {
    "identity": {"LITEAI_JWKS_URL"},
    "metadata": {"LITEAI_JWKS_URL", "GRAVITINO_URL"},
    "data-pipeline": {"LITEAI_JWKS_URL", "JOBS_DIR", "OSS_ENDPOINT", "OSS_ACCESS_KEY",
                      "OSS_SECRET_KEY", "OSS_REGION", "DATA_BUCKET", "AUDIT_BUCKET", "DJ_BIN"},
    "gateway": {"IDENTITY_ORG_URL", "METADATA_URL", "DATA_PIPELINE_URL", "LITEAI_JWKS_URL",
                "BFF_SESSION_KEY", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_ISSUER",
                "BFF_REDIRECT_URI"},
}

@pytest.mark.parametrize("svc,keys", _BASELINE.items())
def test_export_env_matches_baseline(svc, keys):
    s = load_settings("local")
    env = export_env(s, svc)
    assert set(env.keys()) == keys, f"{svc} 键集偏离回归基线"
    assert all(v for v in env.values()), f"{svc} 有空值"

def test_data_pipeline_subset_covers_worker_oss_set():
    s = load_settings("local")
    env = export_env(s, "data-pipeline")
    for k in ("OSS_ENDPOINT", "OSS_ACCESS_KEY", "OSS_SECRET_KEY", "DATA_BUCKET", "AUDIT_BUCKET"):
        assert k in env

def test_data_pipeline_paths_are_absolute():
    s = load_settings("local")
    env = export_env(s, "data-pipeline")
    assert env["JOBS_DIR"].startswith("/")
    assert env["DJ_BIN"].startswith("/")


import subprocess, sys
from pathlib import Path

def test_load_env_cli_emits_gateway_keys():
    root = Path(__file__).resolve().parents[2]
    out = subprocess.run([sys.executable, str(root / "scripts/load_env.py"), "gateway"],
                         capture_output=True, text=True, env={**os.environ, "LITEAI_ENV": "local"})
    assert out.returncode == 0, out.stderr
    emitted = dict(tok.split("=", 1) for tok in out.stdout.split())
    assert "BFF_SESSION_KEY" in emitted and "IDENTITY_ORG_URL" in emitted
