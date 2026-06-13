from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse

from libs.authz.engine import can
from libs.authz.types import Resource
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId, GroupId
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request


def _metalake(ent: str) -> str:
    return ent.replace("-", "_")


def _enterprise(ctx: Context) -> str:
    if not ctx.memberships:
        raise HTTPException(status_code=403, detail="no enterprise membership")
    return ctx.memberships[0].enterprise_id  # v1 单企业


def _resource(ent: str, fs: dict) -> Resource:
    p = fs.get("properties", {})
    return Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                    group_id=GroupId(p["owner_group"]), scope=p.get("scope", "private"),
                    owner=p.get("owner_user"))


def _dataset(ent: str, fs: dict) -> dict:
    p, a = fs.get("properties", {}), fs.get("audit", {})
    return {"name": fs["name"], "enterprise_id": ent, "group_id": p["owner_group"],
            "owner": p.get("owner_user"), "scope": p.get("scope", "private"),
            "location": fs.get("storageLocation", ""), "comment": fs.get("comment") or None,
            "created_at": a.get("createTime"), "created_by": a.get("creator")}


def build_app(gravitino):
    app = make_service_app(title="metadata-service", version="0.1.0")

    @app.get("/v1/catalogs")
    def catalogs(ctx: Context = Depends(context_from_request)):
        return {"names": gravitino.list_catalogs(_metalake(_enterprise(ctx)))}

    @app.get("/v1/catalogs/{catalog}/schemas")
    def schemas(catalog: str, ctx: Context = Depends(context_from_request)):
        return {"names": gravitino.list_schemas(_metalake(_enterprise(ctx)), catalog)}

    @app.get("/v1/catalogs/{catalog}/schemas/{schema}/datasets")
    def list_ds(catalog: str, schema: str, ctx: Context = Depends(context_from_request)):
        ent = _enterprise(ctx)
        ml = _metalake(ent)
        out = []
        for name in gravitino.list_filesets(ml, catalog, schema):
            fs = gravitino.get_fileset(ml, catalog, schema, name)
            if can(ctx, "dataset.read", _resource(ent, fs)).allow:
                out.append(_dataset(ent, fs))
        return {"datasets": out}

    @app.get("/v1/catalogs/{catalog}/schemas/{schema}/datasets/{name}")
    def get_ds(catalog: str, schema: str, name: str, ctx: Context = Depends(context_from_request)):
        ent = _enterprise(ctx)
        ml = _metalake(ent)
        try:
            fs = gravitino.get_fileset(ml, catalog, schema, name)
        except Exception:
            raise HTTPException(status_code=404, detail="not found")
        d = can(ctx, "dataset.read", _resource(ent, fs))
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        return _dataset(ent, fs)

    @app.post("/v1/catalogs/{catalog}/schemas/{schema}/datasets", status_code=201)
    def register(catalog: str, schema: str, body: dict, ctx: Context = Depends(context_from_request)):
        ent = _enterprise(ctx)
        ml = _metalake(ent)
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                       group_id=GroupId(body["group_id"]), scope=body.get("scope", "private"), owner=ctx.user)
        d = can(ctx, "dataset.register", res)
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        fs = gravitino.create_fileset(ml, catalog, schema, body["name"], body["location"],
                                      comment=body.get("comment", ""),
                                      properties={"owner_group": body["group_id"], "owner_user": ctx.user,
                                                  "scope": body.get("scope", "private")})
        return _dataset(ent, fs)

    return app
