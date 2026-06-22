from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse

from libs.authz.engine import can
from libs.authz.types import Resource
from libs.contracts_gen.metadata_models import RegisterDataset
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId, GroupId
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request, enterprise_of
from services.metadata_service.gravitino import GravitinoError, _is_conflict


def _metalake(ent: str) -> str:
    return ent.replace("-", "_")


def _scope_value(scope) -> str:
    # RegisterDataset.scope 可能是 Scope 枚举(显式传)或默认字符串 'private'(未传)
    return getattr(scope, "value", scope) or "private"


def _owner_group(fs: dict) -> str | None:
    """fileset 的归属组。缺失 = 不可归属(带外/未治理 fileset)→ 调用方按 fail-closed 处理。"""
    return fs.get("properties", {}).get("owner_group")


def _resource(ent: str, fs: dict) -> Resource:
    p = fs.get("properties", {})
    return Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                    group_id=GroupId(p.get("owner_group", "")), scope=p.get("scope", "private"),
                    owner=p.get("owner_user"))


def _dataset(ent: str, fs: dict) -> dict:
    p, a = fs.get("properties", {}), fs.get("audit", {})

    def _int(v):
        return int(v) if v not in (None, "") else None

    return {"name": fs["name"], "enterprise_id": ent, "group_id": p.get("owner_group"),
            "owner": p.get("owner_user"), "scope": p.get("scope", "private"),
            "location": fs.get("storageLocation", ""), "comment": fs.get("comment") or None,
            "created_at": a.get("createTime"), "created_by": a.get("creator"),
            "format": p.get("format") or None,
            "num_samples": _int(p.get("num_samples")),
            "size_bytes": _int(p.get("size_bytes"))}


def build_app(gravitino):
    app = make_service_app(title="metadata-service", version="0.1.0")

    @app.get("/v1/catalogs")
    def catalogs(ctx: Context = Depends(context_from_request)):
        return {"names": gravitino.list_catalogs(_metalake(enterprise_of(ctx)))}

    @app.get("/v1/catalogs/{catalog}/schemas")
    def schemas(catalog: str, ctx: Context = Depends(context_from_request)):
        return {"names": gravitino.list_schemas(_metalake(enterprise_of(ctx)), catalog)}

    @app.get("/v1/catalogs/{catalog}/schemas/{schema}/datasets")
    def list_ds(catalog: str, schema: str, ctx: Context = Depends(context_from_request)):
        ent = enterprise_of(ctx)
        ml = _metalake(ent)
        out = []
        for name in gravitino.list_filesets(ml, catalog, schema):  # N+1:list 仅返回名,逐个 get(ADR-016 规模可忽略)
            fs = gravitino.get_fileset(ml, catalog, schema, name)
            if not _owner_group(fs):       # 不可归属 → fail-closed,不列出
                continue
            if can(ctx, "dataset.read", _resource(ent, fs)).allow:
                out.append(_dataset(ent, fs))
        return {"datasets": out}

    @app.get("/v1/catalogs/{catalog}/schemas/{schema}/datasets/{name}")
    def get_ds(catalog: str, schema: str, name: str, ctx: Context = Depends(context_from_request)):
        ent = enterprise_of(ctx)
        ml = _metalake(ent)
        try:
            fs = gravitino.get_fileset(ml, catalog, schema, name)
        except Exception:
            raise HTTPException(status_code=404, detail="not found")
        if not _owner_group(fs):           # 不可归属 → fail-closed deny(不崩成 500)
            return JSONResponse(status_code=403, content={"reason": "unattributed resource"})
        d = can(ctx, "dataset.read", _resource(ent, fs))
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        return _dataset(ent, fs)

    @app.post("/v1/catalogs/{catalog}/schemas/{schema}/datasets", status_code=201)
    def register(catalog: str, schema: str, body: RegisterDataset,
                 ctx: Context = Depends(context_from_request)):
        ent = enterprise_of(ctx)
        ml = _metalake(ent)
        scope = _scope_value(body.scope)
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                       group_id=GroupId(body.group_id), scope=scope, owner=ctx.user)
        d = can(ctx, "dataset.register", res)
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        props = {"owner_group": body.group_id, "owner_user": ctx.user, "scope": scope}
        if body.format is not None:
            props["format"] = body.format
        if body.num_samples is not None:
            props["num_samples"] = str(body.num_samples)
        if body.size_bytes is not None:
            props["size_bytes"] = str(body.size_bytes)
        try:
            fs = gravitino.create_fileset(ml, catalog, schema, body.name, body.location,
                                          comment=body.comment or "", properties=props)
        except GravitinoError as e:
            if _is_conflict(e):            # 已存在 → 409 Conflict(不逃逸成 500)
                return JSONResponse(status_code=409, content={"reason": "dataset already exists"})
            raise
        return _dataset(ent, fs)

    return app
