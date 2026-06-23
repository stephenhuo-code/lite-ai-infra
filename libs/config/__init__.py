"""单一配置源:configs/<env>.yaml → 解析 + 展开 ${VAR} → 强类型 Settings。
设计见 docs/superpowers/plans/2026-06-23-env-config-persistence/design.md(ADR-021)。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_PLACEHOLDER = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$")
_REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """配置缺失/占位未注入/档不存在。"""


@dataclass
class _Services:
    identity_url: str
    metadata_url: str
    data_pipeline_url: str
    gateway_url: str


@dataclass
class _Auth:
    jwks_url: str


@dataclass
class _Bff:
    session_key: str
    redirect_uri: str
    oidc_client_id: str
    oidc_client_secret: str
    oidc_issuer: str


@dataclass
class _Oss:
    endpoint: str
    access_key: str
    secret_key: str
    region: str
    data_bucket: str
    audit_bucket: str
    session_token: str | None = None
    upload_url_ttl: int | None = None


@dataclass
class _Gravitino:
    url: str


@dataclass
class _Pipeline:
    jobs_dir: str
    dj_bin: str
    raw_dir: str | None = None


@dataclass
class Settings:
    env: str
    services: _Services
    auth: _Auth
    bff: _Bff
    oss: _Oss
    gravitino: _Gravitino
    pipeline: _Pipeline


def _expand(value, missing: list[str]):
    """字面值直返;${VAR} 查 os.environ,未命中记入 missing(后续按 env 决定是否致命)。"""
    if isinstance(value, str):
        m = _PLACEHOLDER.match(value)
        if m:
            var = m.group(1)
            got = os.environ.get(var)
            if got is None:
                missing.append(var)
                return None
            return got
    return value


def load_settings(env: str | None = None, root: Path | None = None) -> Settings:
    """读 configs/<env>.yaml → 展开 ${VAR} → Settings。
    env 缺省取 $LITEAI_ENV 再缺省 'local'。
    任何档出现未命中占位 → ConfigError(指出缺哪些,对齐 ${VAR:?} 语义)。
    local 档本不该有占位,出现即配置写错,同样报错。"""
    env = env or os.environ.get("LITEAI_ENV") or "local"
    root = root or _REPO_ROOT
    path = Path(root) / "configs" / f"{env}.yaml"
    if not path.exists():
        raise ConfigError(f"配置档不存在: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    missing: list[str] = []

    def grp(name):
        return {k: _expand(v, missing) for k, v in (data.get(name) or {}).items()}

    settings = Settings(
        env=data.get("env", env),
        services=_Services(**grp("services")),
        auth=_Auth(**grp("auth")),
        bff=_Bff(**grp("bff")),
        oss=_Oss(**grp("oss")),
        gravitino=_Gravitino(**grp("gravitino")),
        pipeline=_Pipeline(**grp("pipeline")),
    )
    if missing:
        raise ConfigError(
            f"[{env}] 必需配置占位未注入: {', '.join(sorted(set(missing)))} "
            f"(经环境变量或外部 secret 提供;{env} 档不得静默用空值)"
        )
    return settings
