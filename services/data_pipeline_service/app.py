from __future__ import annotations
import uuid
from datetime import datetime, timezone
from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.audit.oss_audit import AuditWriter, AuditEvent
from libs.contracts_gen.data_pipeline_models import PrepareJobRequest
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId, GroupId
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request, enterprise_of   # enterprise_of 本 plan 抽自 metadata-service
from services.data_pipeline_service.jobs import JobSpec

def _audit_deny(audit: AuditWriter, ctx: Context, ent: str, gid: str, dataset: str, reason: str) -> None:
    audit.write(AuditEvent(ts=datetime.now(timezone.utc).isoformat(), enterprise_id=ent, group_id=gid,
                           actor_user=ctx.user, actor_role=ctx.role_in(EnterpriseId(ent), GroupId(gid)) or "none",
                           action="data.prepare", resource_uri=f"dataset/{dataset}", decision="deny",
                           override=False, reason=reason, metadata={}))

def build_app(runner, audit: AuditWriter):
    app = make_service_app(title="data-pipeline-service", version="0.1.0")

    @app.post("/v1/data/prepare", status_code=202)
    def prepare(body: PrepareJobRequest, ctx: Context = Depends(context_from_request)):
        ent = enterprise_of(ctx)
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent), group_id=GroupId(body.group_id))
        d = can(ctx, "data.prepare", res)
        if not d.allow:                       # deny → 零副作用 + 审计
            _audit_deny(audit, ctx, ent, body.group_id, body.dataset, d.reason)
            return JSONResponse(status_code=403, content={"reason": d.reason})
        job_id = "job-" + uuid.uuid4().hex[:16]      # 服务端不透明 id(不变量 3)
        spec = JobSpec(job_id=job_id, dataset=body.dataset, group_id=body.group_id, enterprise_id=ent,
                       role=ctx.role_in(EnterpriseId(ent), GroupId(body.group_id)) or "member",
                       sub=ctx.user, tar_dir=body.tar_dir, np=body.np or 3, process=body.process)
        runner.submit(spec)
        return runner.get(job_id)

    @app.get("/v1/data/jobs")
    def list_jobs(status: str | None = None, limit: int = 50, offset: int = 0,
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

    return app
