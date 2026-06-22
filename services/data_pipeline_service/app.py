from __future__ import annotations
import uuid
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.audit.oss_audit import AuditWriter, AuditEvent
from libs.contracts_gen.data_pipeline_models import (
    PrepareJobRequest, RawUploadRequest, CompleteUploadRequest)
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId, GroupId
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request, enterprise_of   # enterprise_of 本 plan 抽自 metadata-service
from services.data_pipeline_service.jobs import JobSpec
from services.data_pipeline_service.upload import ObjectMissing

def _audit(audit: AuditWriter, ctx: Context, ent: str, gid: str, resource_uri: str,
           action: str, decision: str, reason: str, metadata: dict | None = None) -> None:
    audit.write(AuditEvent(ts=datetime.now(timezone.utc).isoformat(), enterprise_id=ent, group_id=gid,
                           actor_user=ctx.user, actor_role=ctx.role_in(EnterpriseId(ent), GroupId(gid)) or "none",
                           action=action, resource_uri=resource_uri, decision=decision,
                           override=False, reason=reason, metadata=metadata or {}))

def build_app(runner, audit: AuditWriter, uploader=None):
    app = make_service_app(title="data-pipeline-service", version="0.1.0")

    @app.post("/v1/data/prepare", status_code=202)
    def prepare(body: PrepareJobRequest, ctx: Context = Depends(context_from_request)):
        ent = enterprise_of(ctx)
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent), group_id=GroupId(body.group_id))
        d = can(ctx, "data.prepare", res)
        if not d.allow:                       # deny → 零副作用 + 审计
            _audit(audit, ctx, ent, body.group_id, f"dataset/{body.dataset}", "data.prepare", "deny", d.reason)
            return JSONResponse(status_code=403, content={"reason": d.reason})
        job_id = "job-" + uuid.uuid4().hex[:16]      # 服务端不透明 id(不变量 3)
        spec = JobSpec(job_id=job_id, dataset=body.dataset, group_id=body.group_id, enterprise_id=ent,
                       role=ctx.role_in(EnterpriseId(ent), GroupId(body.group_id)) or "member",
                       sub=ctx.user, tar_dir=body.tar_dir, np=body.np or 3, process=body.process)
        runner.submit(spec)
        return runner.get(job_id)

    @app.get("/v1/data/jobs")
    def list_jobs(status: str | None = None,
                  limit: int = Query(50, ge=1, le=200),     # 契约 maximum=200,强制(默认不验 schema 边界)
                  offset: int = Query(0, ge=0),             # 防负 offset 取尾片(契约 default=0)
                  ctx: Context = Depends(context_from_request)):
        ent = enterprise_of(ctx)
        visible = []
        for j in runner.list_jobs():                       # 纯取数(含 enterprise_id/group_id 投影)
            je, jg = j.get("enterprise_id"), j.get("group_id")
            if je is None or je != ent:                    # I-2 fail-closed:spec 缺失/跨企业 → 跳过
                continue
            res = Resource(kind="job", enterprise_id=EnterpriseId(ent), group_id=GroupId(jg))
            if not can(ctx, "data.read", res).allow:       # I-1:必经 can() 按组过滤(跨组不可见)
                continue
            if status and j.get("status") != status:       # status 过滤
                continue
            visible.append(j)
        total = len(visible)                               # 过滤后总数(非全量、非页大小)
        return {"jobs": visible[offset: offset + limit], "total": total}

    @app.get("/v1/data/jobs/{job_id}")
    def get_job(job_id: str, ctx: Context = Depends(context_from_request)):
        ent = enterprise_of(ctx)
        job = runner.get(job_id)
        if job is None or job["enterprise_id"] != ent:
            raise HTTPException(status_code=404, detail="not found")   # 跨企业=不存在(不泄漏)
        res = Resource(kind="job", enterprise_id=EnterpriseId(ent), group_id=GroupId(job["group_id"]))
        if not can(ctx, "data.read", res).allow:                      # 跨组 → 403
            return JSONResponse(status_code=403, content={"reason": "cross-group"})
        return job

    @app.post("/v1/data/raw")
    def request_upload(body: RawUploadRequest, ctx: Context = Depends(context_from_request)):
        if uploader is None:
            raise HTTPException(status_code=503, detail="upload not configured")
        ent = enterprise_of(ctx)
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent), group_id=GroupId(body.group_id))
        d = can(ctx, "data.upload", res)
        if not d.allow:                                       # deny → 零副作用 + 审计
            _audit(audit, ctx, ent, body.group_id, f"raw/{body.dataset}", "data.upload", "deny", d.reason)
            return JSONResponse(status_code=403, content={"reason": d.reason})
        try:
            grant = uploader.create_grant(name=body.dataset, enterprise_id=ent, group_id=body.group_id,
                                          sub=ctx.user, filename=body.filename,
                                          multipart=bool(body.multipart), parts=body.parts)
        except ValueError as e:                               # 文件名/数据集名非法
            return JSONResponse(status_code=400, content={"reason": str(e)})
        # presign allow 审计带 key+TTL+raw_id(ADR-020 I-2):GC 扫 pending 超时时可据此对账
        # "授权了但结果未知"的中间态(字节已落 OSS 但 complete 丢失)。
        _audit(audit, ctx, ent, body.group_id, f"raw/{body.dataset}", "data.upload", "allow", "",
               metadata={"raw_id": grant["raw_id"], "oss_key": grant["oss_key"], "expires_in": grant["expires_in"]})
        return grant

    @app.post("/v1/data/raw/{raw_id}/complete")
    def complete_upload(raw_id: str, body: CompleteUploadRequest | None = None,
                        ctx: Context = Depends(context_from_request)):
        if uploader is None:
            raise HTTPException(status_code=503, detail="upload not configured")
        ent = enterprise_of(ctx)
        rec = uploader.get_record(raw_id)
        if rec is None or rec["enterprise_id"] != ent:        # 跨企业=不存在(不泄漏)
            raise HTTPException(status_code=404, detail="not found")
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent), group_id=GroupId(rec["group_id"]))
        if not can(ctx, "data.upload", res).allow:            # 按记录 eid/gid 再 can()(C-2)
            return JSONResponse(status_code=403, content={"reason": "cross-group"})
        parts = [p.model_dump() for p in (body.parts or [])] if body and body.parts else None
        try:
            out = uploader.finalize(raw_id, parts=parts)
        except ObjectMissing as e:
            _audit(audit, ctx, ent, rec["group_id"], f"raw/{rec['name']}", "data.upload", "deny", "object-missing")
            return JSONResponse(status_code=409, content={"reason": str(e)})
        _audit(audit, ctx, ent, rec["group_id"], f"raw/{rec['name']}", "data.upload", "allow", "complete",
               metadata={"raw_id": raw_id, "oss_key": rec["oss_key"], "size": out.get("size")})
        return out

    @app.get("/v1/data/raw")
    def list_raw(status: str | None = None,
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 ctx: Context = Depends(context_from_request)):
        if uploader is None:
            raise HTTPException(status_code=503, detail="upload not configured")
        ent = enterprise_of(ctx)
        visible = []
        for r in uploader.list_raw():
            re_, rg = r.get("enterprise_id"), r.get("group_id")
            if re_ is None or re_ != ent:                     # fail-closed:缺失/跨企业 → 跳过
                continue
            res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent), group_id=GroupId(rg))
            if not can(ctx, "data.read", res).allow:          # 必经 can() 按组过滤
                continue
            if status and r.get("status") != status:
                continue
            visible.append(r)
        return {"raw": visible[offset: offset + limit], "total": len(visible)}

    return app
