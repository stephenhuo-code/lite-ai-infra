"""单一配置源:configs/<env>.yaml → 解析 + 展开 ${VAR} → 强类型 Settings。
设计见 docs/superpowers/plans/2026-06-23-env-config-persistence/design.md(ADR-021)。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_PLACEHOLDER = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$")
# I-3 护栏:发射值不得含空白或 glob 元字符(* ? [),否则会被无引号词分割注入破坏。
_UNSAFE = re.compile(r"[\s*?\[]")
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

    try:
        settings = Settings(
            env=data.get("env", env),
            services=_Services(**grp("services")),
            auth=_Auth(**grp("auth")),
            bff=_Bff(**grp("bff")),
            oss=_Oss(**grp("oss")),
            gravitino=_Gravitino(**grp("gravitino")),
            pipeline=_Pipeline(**grp("pipeline")),
        )
    except TypeError as e:
        raise ConfigError(
            f"[{env}] 配置结构错误(缺字段或多余字段): {e}"
        ) from e
    if missing:
        raise ConfigError(
            f"[{env}] 必需配置占位未注入: {', '.join(sorted(set(missing)))} "
            f"(经环境变量或外部 secret 提供;{env} 档不得静默用空值)"
        )
    return settings


# --- 桥接:Settings → 服务现有 env 名(回归基线 1:1) ---

def _abs(path: str | None) -> str | None:
    if path is None:
        return None
    pp = Path(path)
    return str(pp if pp.is_absolute() else (_REPO_ROOT / pp))


def _flat(s: Settings) -> dict[str, str | None]:
    """扁平 env 名 → 取值(单一映射表;新增 env 在此加一行)。

    不变量:值不得含空格或 glob 元字符(* ? [)。消费方 scripts/dev_services.sh
    与 Makefile run-* 用无引号 `env $(load_env.py svc)` 词分割注入,含空格/glob 的值
    会被错误切分。该不变量现已由 export_env 强制校验(_UNSAFE 正则,违反即 ConfigError),
    不再只是文档约定。今所有值均满足。若未来配置值变复杂(连接串/带空格密码),改用
    load_env.py 的 `--export` + `eval "$(... --export)"` 模式以规避词分割。
    """
    p = s.pipeline
    return {
        "LITEAI_JWKS_URL": s.auth.jwks_url,
        "GRAVITINO_URL": s.gravitino.url,
        "IDENTITY_ORG_URL": s.services.identity_url,
        "METADATA_URL": s.services.metadata_url,
        "DATA_PIPELINE_URL": s.services.data_pipeline_url,
        "BFF_SESSION_KEY": s.bff.session_key,
        "OIDC_CLIENT_ID": s.bff.oidc_client_id,
        "OIDC_CLIENT_SECRET": s.bff.oidc_client_secret,
        "OIDC_ISSUER": s.bff.oidc_issuer,
        "BFF_REDIRECT_URI": s.bff.redirect_uri,
        "OSS_ENDPOINT": s.oss.endpoint,
        "OSS_ACCESS_KEY": s.oss.access_key,
        "OSS_SECRET_KEY": s.oss.secret_key,
        "OSS_REGION": s.oss.region,
        "DATA_BUCKET": s.oss.data_bucket,
        "AUDIT_BUCKET": s.oss.audit_bucket,
        "JOBS_DIR": _abs(p.jobs_dir),
        "DJ_BIN": _abs(p.dj_bin),
    }


# 每服务注入子集 == 现 _env_for 实测基线(顺序无关)
SERVICE_ENV_KEYS: dict[str, list[str]] = {
    "identity": ["LITEAI_JWKS_URL"],
    "metadata": ["LITEAI_JWKS_URL", "GRAVITINO_URL", "OSS_ENDPOINT", "OSS_ACCESS_KEY",
                 "OSS_SECRET_KEY", "DATA_BUCKET"],
    "data-pipeline": ["LITEAI_JWKS_URL", "JOBS_DIR", "OSS_ENDPOINT", "OSS_ACCESS_KEY",
                      "OSS_SECRET_KEY", "OSS_REGION", "DATA_BUCKET", "AUDIT_BUCKET", "DJ_BIN"],
    "gateway": ["IDENTITY_ORG_URL", "METADATA_URL", "DATA_PIPELINE_URL", "LITEAI_JWKS_URL",
                "BFF_SESSION_KEY", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_ISSUER",
                "BFF_REDIRECT_URI"],
}


def export_env(s: Settings, service: str) -> dict[str, str]:
    """返回该服务启动所需的扁平 env(== 现 _env_for 注入集)。"""
    if service not in SERVICE_ENV_KEYS:
        raise ConfigError(f"未知服务: {service}(可选:{', '.join(SERVICE_ENV_KEYS)})")
    flat = _flat(s)
    out = {}
    for k in SERVICE_ENV_KEYS[service]:
        v = flat.get(k)
        if v is None:
            raise ConfigError(f"服务 {service} 所需配置 {k} 为空(env={s.env})")
        out[k] = str(v)
        if _UNSAFE.search(out[k]):
            raise ConfigError(
                f"服务 {service} 配置 {k} 含空白或 glob 元字符(* ? [),"
                f"会被无引号 `env $(load_env.py {service})` 词分割注入破坏(I-3 护栏);"
                f"如确需复杂值,请改用 load_env.py --export + eval 模式(env={s.env})"
            )
    return out
