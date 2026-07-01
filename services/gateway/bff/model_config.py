# services/gateway/bff/model_config.py
# 模型配置 BFF(ADR-028:每企业统一管模型凭据)。enterprise-admin 在一处配本企业各 provider 的
# 凭据(订阅 token / API key + 可选 base_url);写进【本企业】的 gitignored 文件
# secrets/model-config/<alias>.json(env 名→值的扁平 map),omnigent 容器只读挂载该目录,
# 于每次 managed 会话 provision 时按 session.labels.enterprise_id 读本企业文件注入沙箱(M1 fork)。
#
# 红线:
#   - 授权只经 can()(model-config:read/write/delete → enterprise-admin);跨企业硬隔离(只碰自己 alias.json)。
#   - 凭据【值】绝不 log / 审计 / 返回 —— 只回状态/元数据(configured/auth_type/has_base_url)。
#   - 值必须字面(reject ${}/$VAR,同 omnigent fork 白名单)——绝不外泄服务端 env、绝不让 fork 400。
#   - alias 经 _resolve_ctx 的 _ALIAS_RE guard(无 "_",纯 ASCII 字母数字+连字符)→ 文件名安全、无路径穿越。
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from libs.audit.oss_audit import AuditEvent, AuditWriter
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId

from services.gateway.bff.omnigent_proxy import _ENV_REF_RE, _resolve_ctx

# ── Provider 定义表 ──────────────────────────────────────────────────────────
# 每 provider:auth 选项(auth_type → 注入的 env 变量名)+ 可选 base_url env 变量名。
# 这些 env 名字**正是** M1 fork 白名单注入沙箱的名字(sandbox.docker.env 名单)。
# 每 provider 的多个 auth 选项**互斥**(只写一个;写一个即删另一个),因为它们冲突
# (如 claude 的订阅 CLAUDE_CODE_OAUTH_TOKEN 与 ANTHROPIC_API_KEY 同注会冲突)。
_PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "auth": {"subscription": "CLAUDE_CODE_OAUTH_TOKEN", "api_key": "ANTHROPIC_API_KEY"},
        "base_url_env": "ANTHROPIC_BASE_URL",
    },
    "openai": {
        "auth": {"api_key": "OPENAI_API_KEY", "subscription": "CODEX_ACCESS_TOKEN"},
        "base_url_env": "OPENAI_BASE_URL",
    },
    "gemini": {
        "auth": {"api_key": "GEMINI_API_KEY"},
        "base_url_env": None,
    },
}

# 该 provider 会占用的所有 env 名字(所有 auth 选项 + base_url)——写一个 auth 前先清掉其余,
# 保证互斥 auth 绝不同存,且状态读取只看这些名字。
def _provider_env_names(provider: str) -> set[str]:
    p = _PROVIDERS[provider]
    names = set(p["auth"].values())
    if p["base_url_env"]:
        names.add(p["base_url_env"])
    return names


def _is_env_ref(value: str) -> bool:
    """值是否含 ${...}/$VAR 引用(fork 白名单会拒,BFF 先拒:防外泄服务端 env)。"""
    return bool(_ENV_REF_RE.search(value))


def _store_root() -> Path:
    """本企业凭据文件目录 = <repo-root>/secrets/model-config/(网关进程从 repo root 跑)。
    MODEL_CONFIG_DIR env 可覆盖(测试指向临时目录,绝不碰真 secrets/)。这与 omnigent 只读挂载的
    host 目录 secrets/model-config 是**同一个**。缺失则建(gitignored)。"""
    root = Path(os.getenv("MODEL_CONFIG_DIR", "secrets/model-config"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _enterprise_file(alias: str) -> Path:
    # alias 已过 _ALIAS_RE(纯 [a-zA-Z0-9-],无 "_"/"."/"/"),故 <alias>.json 无路径穿越、稳定唯一。
    return _store_root() / f"{alias}.json"


def _load_creds(alias: str) -> dict[str, str]:
    """读本企业 env-map(缺文件/坏 JSON → 空)。绝不跨 alias 读。"""
    p = _enterprise_file(alias)
    if not p.exists():
        return {}
    try:
        obj = json.loads(p.read_text())
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _write_creds(alias: str, creds: dict[str, str]) -> None:
    """原子写(temp + os.replace,镜像 raw_store):读者绝不见半写文件。0600 权限(含密钥)。"""
    p = _enterprise_file(alias)
    tmp = p.parent / f".{alias}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(creds, ensure_ascii=False, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _provider_status(provider: str, creds: dict[str, str]) -> dict:
    """据 env-map 算某 provider 的**状态**(绝不含值):configured / auth_type / has_base_url。"""
    p = _PROVIDERS[provider]
    auth_type = None
    for at, env_name in p["auth"].items():
        if creds.get(env_name):
            auth_type = at
            break
    base_url_env = p["base_url_env"]
    has_base_url = bool(base_url_env and creds.get(base_url_env))
    return {"provider": provider, "configured": auth_type is not None,
            "auth_type": auth_type, "has_base_url": has_base_url}


def _all_status(creds: dict[str, str]) -> list[dict]:
    return [_provider_status(pr, creds) for pr in _PROVIDERS]


def make_model_config_router(*, claims,
                             audit_writer: AuditWriter | None = None) -> APIRouter:
    """模型配置路由(/v1/ws/model-config*),受会话中间件保护 + CSRF。复用 _resolve_ctx
    (含 _ALIAS_RE guard,与智能体库一致地拒 "_"-坏 alias)。授权经 can()(enterprise-admin)。"""
    router = APIRouter()

    def _audit(action: str, ctx: Context, alias: str, provider: str,
               auth_type: str | None, has_base_url: bool, decision: str) -> None:
        # 审计**绝不**落凭据值(红线 §5.2);仅 provider / auth_type / has_base_url 元数据。
        if audit_writer is None:
            return
        audit_writer.write(AuditEvent(
            ts=datetime.now(timezone.utc).isoformat(), enterprise_id=alias,
            actor_user=ctx.user, actor_role=ctx.role_in(EnterpriseId(alias)) or "none",
            action=action, resource_uri=f"model-config/{provider}", decision=decision,
            override=False, reason="",
            metadata={"provider": provider, "auth_type": auth_type,
                      "has_base_url": has_base_url}))

    @router.get("/v1/ws/model-config")
    def get_config(request: Request):
        # 读本企业各 provider 状态(configured/auth_type/has_base_url)。绝不返回密钥值。admin-only。
        email, ctx, alias, err = _resolve_ctx(request, claims)
        if err:
            return err
        d = can(ctx, "model-config:read", Resource(kind="model-config",
                                                   enterprise_id=EnterpriseId(alias), owner=None))
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        creds = _load_creds(alias)
        return JSONResponse(status_code=200, content={"providers": _all_status(creds)})

    @router.put("/v1/ws/model-config/{provider}")
    async def put_config(provider: str, request: Request):
        # 写本企业某 provider 的凭据:enterprise-admin(can())→ 校验 provider+auth_type → 字面值 →
        # 原子写本企业文件(设选定 env,删另一 auth 选项的 env,设/清 base_url env)→ 审计(无值)→ 回状态。
        email, ctx, alias, err = _resolve_ctx(request, claims)
        if err:
            return err
        d = can(ctx, "model-config:write", Resource(kind="model-config",
                                                    enterprise_id=EnterpriseId(alias), owner=None))
        if not d.allow:           # 非企业管理员 → 403,绝不写文件(can() 先于任何写)
            return JSONResponse(status_code=403, content={"reason": d.reason})
        if provider not in _PROVIDERS:
            return JSONResponse(status_code=400, content={"reason": f"unknown provider: {provider}"})
        try:
            body = await request.json()
        except Exception:
            body = {}
        auth_type = ((body or {}).get("auth_type") or "").strip()
        value = (body or {}).get("value") or ""
        base_url = ((body or {}).get("base_url") or "").strip() or None
        pdef = _PROVIDERS[provider]
        if auth_type not in pdef["auth"]:
            return JSONResponse(status_code=400,
                                content={"reason": f"unsupported auth_type for {provider}: {auth_type}"})
        if not value or not value.strip():
            return JSONResponse(status_code=400, content={"reason": "value required"})
        # 字面值门(红线):值 / base_url 含 ${}/$VAR 引用 → 拒(绝不外泄服务端 env、绝不让 fork 400)。
        if _is_env_ref(value):
            return JSONResponse(status_code=400,
                                content={"reason": "value must be a literal (no ${} / $VAR refs)"})
        if base_url and (_is_env_ref(base_url)):
            return JSONResponse(status_code=400,
                                content={"reason": "base_url must be a literal (no ${} / $VAR refs)"})
        if base_url and not pdef["base_url_env"]:
            return JSONResponse(status_code=400,
                                content={"reason": f"{provider} does not support base_url"})
        creds = _load_creds(alias)
        # 互斥:先清掉该 provider 的所有 env(所有 auth 选项 + base_url),再写选定的那一个。
        for name in _provider_env_names(provider):
            creds.pop(name, None)
        creds[pdef["auth"][auth_type]] = value
        if pdef["base_url_env"] and base_url:
            creds[pdef["base_url_env"]] = base_url
        _write_creds(alias, creds)
        _audit("model-config:update", ctx, alias, provider, auth_type,
               has_base_url=bool(base_url), decision="allow")
        # 回状态(绝不回显值)。
        return JSONResponse(status_code=200,
                            content={"providers": _all_status(creds),
                                     "provider": _provider_status(provider, creds)})

    @router.delete("/v1/ws/model-config/{provider}")
    def delete_config(provider: str, request: Request):
        # 删本企业某 provider 的所有凭据 env → 原子写 → 审计。
        email, ctx, alias, err = _resolve_ctx(request, claims)
        if err:
            return err
        d = can(ctx, "model-config:delete", Resource(kind="model-config",
                                                     enterprise_id=EnterpriseId(alias), owner=None))
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        if provider not in _PROVIDERS:
            return JSONResponse(status_code=400, content={"reason": f"unknown provider: {provider}"})
        creds = _load_creds(alias)
        for name in _provider_env_names(provider):
            creds.pop(name, None)
        _write_creds(alias, creds)
        _audit("model-config:delete", ctx, alias, provider, None,
               has_base_url=False, decision="allow")
        return JSONResponse(status_code=200,
                            content={"providers": _all_status(creds),
                                     "provider": _provider_status(provider, creds)})

    return router
