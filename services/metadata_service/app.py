from __future__ import annotations

import os

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse

from libs.authz.engine import can
from libs.authz.types import Resource
from libs.contracts_gen.metadata_models import RegisterDataset
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request, enterprise_of
from services.metadata_service.gravitino import GravitinoError, _is_conflict


def _metalake(ent: str) -> str:
    return ent.replace("-", "_")


def _scope_value(scope) -> str:
    # RegisterDataset.scope 可能是 Scope 枚举(显式传)或默认字符串 'private'(未传)
    return getattr(scope, "value", scope) or "private"


def _owner_user(fs: dict) -> str | None:
    """fileset 的归属用户(owner,ADR-024)。缺失 = 不可归属(带外/未治理 fileset)→ 调用方按 fail-closed 处理。"""
    return fs.get("properties", {}).get("owner_user")


def _resource(ent: str, fs: dict) -> Resource:
    p = fs.get("properties", {})
    return Resource(kind="dataset", enterprise_id=EnterpriseId(ent),
                    scope=p.get("scope", "private"),
                    owner=p.get("owner_user"))


def _dataset(ent: str, fs: dict) -> dict:
    p, a = fs.get("properties", {}), fs.get("audit", {})

    def _int(v):
        # 整数 property 以字符串存。缺失/空 → None;非数字(带外手改/未来写入方)→ None,
        # 不让一条坏 property 把读投影崩成 500(FR-008 读路径 null-safe)。
        if v in (None, ""):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return {"name": fs["name"], "enterprise_id": ent,
            "owner": p.get("owner_user"), "scope": p.get("scope", "private"),
            "location": fs.get("storageLocation", ""), "comment": fs.get("comment") or None,
            "created_at": a.get("createTime"), "created_by": a.get("creator"),
            "format": p.get("format") or None,
            "num_samples": _int(p.get("num_samples")),
            "size_bytes": _int(p.get("size_bytes")),
            "kind": p.get("kind"),               # raw|processed;缺失=None(前端显未知)
            "derived_from": p.get("derived_from")}


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
        try:
            names = gravitino.list_filesets(ml, catalog, schema)
        except GravitinoError as e:
            if getattr(e, "status", None) == 404:   # 空企业:catalog/schema 未建 → 空列表(非 500)
                return {"datasets": []}
            raise
        out = []
        for name in names:  # N+1:list 仅返回名,逐个 get(ADR-016 规模可忽略)
            fs = gravitino.get_fileset(ml, catalog, schema, name)
            if not _owner_user(fs):        # 不可归属 → fail-closed,不列出
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
        if not _owner_user(fs):            # 不可归属 → fail-closed deny(不崩成 500)
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
                       scope=scope, owner=ctx.user)
        d = can(ctx, "dataset.register", res)
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        from pipelines.data_prep.paths import DatasetPaths
        bucket = os.environ["DATA_BUCKET"]
        kind = getattr(body.kind, "value", body.kind)
        # owner 模型(ADR-024):路径按上传用户钉死(eid/user from ctx),不再按 group
        paths = DatasetPaths(bucket=bucket, enterprise_id=EnterpriseId(ent),
                             user_id=ctx.user, dataset=body.name)
        if kind == "raw":
            location = f"s3://{bucket}/{paths.raw_prefix}"          # 服务端钉死(eid/user from ctx)
            fmt = "webdataset"
        else:  # processed:校验给定 location 必须落在 caller(eid/user from ctx)的 processed/ 前缀内
            location = body.location or ""
            allowed = f"s3://{bucket}/{paths._base}/processed/"
            if not location.startswith(allowed):
                return JSONResponse(status_code=403, content={"reason": "location outside caller prefix"})
            fmt = body.format or "lance"
        props = {"owner_user": ctx.user, "scope": scope,
                 "kind": kind, "format": fmt}
        if body.derived_from:
            props["derived_from"] = body.derived_from
        # num_samples:v1 由 UI 只读取自作业 rows_written(用户不可编辑,FR-010 UI 层强制)。
        # metadata 注册时拿不到作业,故此处接受 body 值但不作服务端权威闸;服务端权威(引用 job_id 回填)= v-next(ADR-023 §6)。
        if body.num_samples is not None:
            props["num_samples"] = str(body.num_samples)
        if body.size_bytes is not None:
            props["size_bytes"] = str(body.size_bytes)
        # scheme 二元性:校验/客户端用 s3://(object_store/lance),但 Gravitino fileset catalog
        # 是 HCFS(Hadoop S3A),只认 s3a://(s3:// → 400 Unsupported scheme)。故只在写 Gravitino
        # 前把头一次 s3:// 换成 s3a://;隔离校验(allowed 前缀)已在转换前用 s3:// 完成,不受影响。
        gravitino_location = location.replace("s3://", "s3a://", 1)
        try:
            fs = gravitino.create_fileset(ml, catalog, schema, body.name, gravitino_location,
                                          comment=body.comment or "", properties=props)
        except GravitinoError as e:
            if _is_conflict(e):            # 已存在 → 409 Conflict(不逃逸成 500)
                return JSONResponse(status_code=409, content={"reason": "dataset already exists"})
            raise
        return _dataset(ent, fs)

    return app
