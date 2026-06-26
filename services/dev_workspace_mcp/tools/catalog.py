# services/dev_workspace_mcp/tools/catalog.py
# 数据探查工具:读 Gravitino fileset 元数据/schema 投影。owner 模型(ADR-024):
# 不可归属 fileset → fail-closed deny;否则 can(dataset.read) 把关(企业硬隔离 + owner)。
# read_schema 为纯函数(ctx + gravitino 注入)→ 可单测;MCP 包装在 app.py。
from __future__ import annotations

from libs.authz.engine import can
from libs.authz.types import Resource
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId
from services._scaffold.auth import enterprise_of

_DENY = {"error": "forbidden"}


def _metalake(ent: str) -> str:
    assert "_" not in ent, ent
    return ent.replace("-", "_")


def read_schema(ctx: Context, gravitino, *, dataset: str,
                catalog: str = "data", schema: str = "datasets") -> dict:
    ent = enterprise_of(ctx)                          # 0/多企业 → 抛(fail-closed)
    try:
        fs = gravitino.get_fileset(_metalake(ent), catalog, schema, dataset)
    except Exception:
        return {"error": "not_found"}
    p = fs.get("properties", {})
    owner = p.get("owner_user")
    if not owner:                                     # 不可归属 → deny
        return _DENY
    res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                   scope=p.get("scope", "private"), owner=owner)
    if not can(ctx, "dataset.read", res).allow:
        return _DENY

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return {"name": fs["name"], "owner": owner, "scope": p.get("scope", "private"),
            "format": p.get("format"), "kind": p.get("kind"),
            "num_samples": _int(p.get("num_samples")),
            "location": fs.get("storageLocation", "")}
