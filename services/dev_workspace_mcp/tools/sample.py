# services/dev_workspace_mcp/tools/sample.py
# 数据集采样:can() 把关(企业硬隔离 + owner,ADR-024),不可归属 fail-closed。
# v1 返回定位 + 格式;真解码采样(webdataset/Lance reader)= v-next(需 reader 依赖)。
from __future__ import annotations

from libs.authz.engine import can
from libs.authz.types import Resource
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId
from services._scaffold.auth import enterprise_of


def _metalake(ent: str) -> str:
    assert "_" not in ent, ent
    return ent.replace("-", "_")


def read_sample(ctx: Context, gravitino, *, dataset: str, n: int = 5,
                catalog: str = "data", schema: str = "datasets") -> dict:
    ent = enterprise_of(ctx)
    try:
        fs = gravitino.get_fileset(_metalake(ent), catalog, schema, dataset)
    except Exception:
        return {"error": "not_found"}
    p = fs.get("properties", {})
    owner = p.get("owner_user")
    if not owner:
        return {"error": "forbidden"}
    if not can(ctx, "dataset.read", Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                                             scope=p.get("scope", "private"), owner=owner)).allow:
        return {"error": "forbidden"}
    return {"dataset": dataset, "n": n, "format": p.get("format"),
            "location": fs.get("storageLocation", ""), "note": "decode-sampling v-next"}
