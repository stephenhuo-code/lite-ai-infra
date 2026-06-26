# services/dev_workspace_mcp/app.py
# http-transport MCP server。URL 形如 /s/<token>/mcp;包裹层把 token 注入 contextvar(身份绑定,
# Task0 实证:omnigent 按注册 URL 原样连、令牌随 URL 抵达),再交给 FastMCP ASGI app。
# 工具调用前置 can()(数据授权唯一出入口,宪法 §2.4)。工具对 agent 显示为 {server}__{tool}
# (Task0:本 server 名 liteai → 如 liteai__whoami)。
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

import subprocess

from pipelines.data_prep.oss_fetch import build_s3
from services.dev_workspace_mcp.identity import current_context, set_current_token
from services.dev_workspace_mcp.tools.git import git_commit as _git_commit
from services.dev_workspace_mcp.tools.git import git_log as _git_log
from services.dev_workspace_mcp.tools.git import git_status as _git_status
from services.dev_workspace_mcp.tools.catalog import read_schema as _read_schema
from services.dev_workspace_mcp.tools.oss import oss_list as _oss_list
from services.dev_workspace_mcp.tools.oss import oss_read as _oss_read
from services.dev_workspace_mcp.tools.pipeline import dj_run_command as _dj_cmd
from services.dev_workspace_mcp.tools.pipeline import scaffold_dj_recipe as _scaffold
from services.dev_workspace_mcp.tools.register import register_processed as _register_processed
from services.dev_workspace_mcp.tools.sample import read_sample as _read_sample
from services.gateway.bff.wstoken import WorkspaceTokenStore
from services.metadata_service.gravitino import GravitinoClient

STORE = WorkspaceTokenStore(ttl_seconds=int(os.getenv("WS_TOKEN_TTL", "3600")))
mcp = FastMCP("liteai")

_GRAVITINO: GravitinoClient | None = None


def _gravitino() -> GravitinoClient:
    # 进程生命周期单例(httpx 连接池),与 metadata_service 同 env。
    global _GRAVITINO
    if _GRAVITINO is None:
        _GRAVITINO = GravitinoClient(base_url=os.environ.get("GRAVITINO_URL", "http://localhost:8091"))
    return _GRAVITINO


@mcp.tool()
def whoami() -> dict:
    """探活 + 身份回显:证明令牌已绑定为某用户/企业。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}        # fail-closed
    ent = ctx.memberships[0].enterprise_id if ctx.memberships else None
    return {"user": ctx.user, "enterprise": str(ent) if ent else None}


@mcp.tool()
def catalog_read_schema(dataset: str, catalog: str = "data", schema: str = "datasets") -> dict:
    """探查数据集:返回 owner/scope/format/kind/num_samples/location(经 can() 把关)。
    对 agent 显示为 liteai__catalog_read_schema。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}
    return _read_schema(ctx, _gravitino(), dataset=dataset, catalog=catalog, schema=schema)


class _OssClient:
    # boto3 s3 → 我们工具期望的 .get(path)/.list(prefix)(path=bucket 内 key)。
    def __init__(self, s3, bucket: str):
        self._s3, self._bucket = s3, bucket

    def get(self, path: str) -> bytes:
        return self._s3.get_object(Bucket=self._bucket, Key=path)["Body"].read()

    def list(self, prefix: str):
        r = self._s3.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        return [o["Key"] for o in r.get("Contents", [])]


_OSS: _OssClient | None = None


def _oss() -> _OssClient:
    global _OSS
    if _OSS is None:
        s3 = build_s3(os.environ["OSS_ENDPOINT"], os.environ["OSS_ACCESS_KEY"], os.environ["OSS_SECRET_KEY"])
        _OSS = _OssClient(s3, os.environ["DATA_BUCKET"])
    return _OSS


class _MetaClient:
    # 注册回 catalog:复用 Gravitino 写(metalake 映射 + s3→s3a,同 metadata_service 语义)。
    def create(self, *, name, location, owner, enterprise, kind, format, derived_from, scope):
        ml = enterprise.replace("-", "_")
        loc = location.replace("s3://", "s3a://", 1)
        props = {"owner_user": owner, "scope": scope, "kind": kind, "format": format}
        if derived_from:
            props["derived_from"] = derived_from
        _gravitino().create_fileset(ml, "data", "datasets", name, loc, comment="", properties=props)
        return {"name": name, "owner": owner}


def _meta() -> _MetaClient:
    return _MetaClient()


@mcp.tool()
def catalog_sample(dataset: str, n: int = 5, catalog: str = "data", schema: str = "datasets") -> dict:
    """采样数据集(can() 把关)。显示为 liteai__catalog_sample。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}
    return _read_sample(ctx, _gravitino(), dataset=dataset, n=n, catalog=catalog, schema=schema)


@mcp.tool()
def oss_read(path: str) -> dict:
    """读 OSS 对象(仅限本企业/owner 前缀)。显示为 liteai__oss_read。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}
    return _oss_read(ctx, _oss(), path=path)


@mcp.tool()
def oss_list(prefix: str = "") -> dict:
    """列 OSS 对象(仅限本企业/owner 前缀)。显示为 liteai__oss_list。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}
    return _oss_list(ctx, _oss(), prefix=prefix)


@mcp.tool()
def register_dataset(name: str, location: str, derived_from: str, fmt: str = "lance") -> dict:
    """把处理后数据集注册回数据目录(owner=本人,越界前缀拒)。显示为 liteai__register_dataset。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}
    return _register_processed(ctx, _meta(), name=name, location=location,
                               derived_from=derived_from, fmt=fmt)


class _LocalRunner:
    # 在工作目录跑 git(沙箱内/本地盘)。OSS↔本地盘的真实同步 = workspace_store 真实 syncer,
    # 形态待 9d Task0 探针(omnigent environment 工作目录路径);此处只负责执行 git。
    def run(self, argv, cwd):
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False).stdout


_RUNNER = _LocalRunner()


def _ws_cwd(ctx) -> str:
    # 本会话工作目录本地路径(env base + owner)。ws 维度的会话→目录映射随持久化落地细化(9d)。
    base = os.environ.get("WS_LOCAL_BASE", "/tmp/liteai-ws")
    return f"{base}/{ctx.user}"


@mcp.tool()
def git_status() -> dict:
    """本地 git 状态(供左树 Git 段)。显示为 liteai__git_status。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}
    return {"changes": _git_status(_RUNNER, cwd=_ws_cwd(ctx))}


@mcp.tool()
def git_log(n: int = 20) -> dict:
    """本地 git 历史。显示为 liteai__git_log。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}
    return {"log": _git_log(_RUNNER, cwd=_ws_cwd(ctx), n=n)}


@mcp.tool()
def git_commit(message: str) -> dict:
    """本地提交(无 push;远端 git 用户自配)。显示为 liteai__git_commit。"""
    ctx = current_context()
    if ctx is None:
        return {"error": "unauthenticated"}
    _git_commit(_RUNNER, cwd=_ws_cwd(ctx), message=message)
    return {"ok": True}


@mcp.tool()
def dj_scaffold(dataset: str, export: str, ops: list, np: int = 4) -> dict:
    """生成 Data-Juicer recipe 到工作目录 + 返回运行命令。显示为 liteai__dj_scaffold。"""
    return {"recipe": _scaffold(dataset=dataset, export=export, ops=ops, np=np),
            "run": _dj_cmd(recipe_path="recipe.py")}


def build_asgi(store: WorkspaceTokenStore = STORE):
    inner = mcp.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            parts = scope.get("path", "").split("/")
            if len(parts) > 2 and parts[1] == "s":
                set_current_token(store, parts[2])
                scope = dict(scope)
                scope["path"] = "/" + "/".join(parts[3:])
        await inner(scope, receive, send)

    return app


asgi = build_asgi()
