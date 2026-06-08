# services/gateway/app.py
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.audit.oss_audit import AuditWriter, AuditEvent
from services.gateway.deps import context_from_request

def _parse_job_ref(ref: str) -> Resource:
    # "e-0099:job-9" -> 跨企业；"job-1" -> 默认本企业 e-0001/g-0001
    if ":" in ref:
        eid, _ = ref.split(":", 1)
        return Resource(kind="job", enterprise_id=eid, group_id=None, owner="someone")
    return Resource(kind="job", enterprise_id="e-0001", group_id="g-0001", owner="u-alice",
                    attrs={"state": "running"})

def build_app(audit: AuditWriter) -> FastAPI:
    """audit 由调用方注入（AuditWriter）：dev/集成传 OssAuditSink+MinIO/OSS；单测传 MemoryAuditSink。"""
    app = FastAPI()

    @app.delete("/v1/jobs/{ref}")
    def delete_job(ref: str, request: Request):
        ctx = context_from_request(request)            # 未认证 → 401
        resource = _parse_job_ref(ref)
        d = can(ctx, "job.delete", resource)            # 唯一出入口
        role = ctx.role_in(resource.enterprise_id, resource.group_id) or "none"
        audit.write(AuditEvent(
            ts=datetime.now(timezone.utc).isoformat(), enterprise_id=resource.enterprise_id,
            group_id=resource.group_id, actor_user=ctx.user, actor_role=role,
            action="job.delete", resource_uri=f"job/{ref}",
            decision="allow" if d.allow else "deny", override=False, reason=d.reason,
            metadata={"ip": request.client.host if request.client else ""}))
        if not d.allow:
            return JSONResponse(status_code=403, content={"reason": d.reason})
        return {"status": "deleted", "ref": ref}
    return app
