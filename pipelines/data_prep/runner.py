# pipelines/data_prep/runner.py
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from libs.identity.context import Context
from libs.identity.ids import EnterpriseId, GroupId
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.audit.oss_audit import AuditWriter, AuditEvent
from pipelines.data_prep.paths import DatasetPaths
from pipelines.data_prep.recipe import build_recipe
from pipelines.data_prep.ingest import wds_to_jsonl
from pipelines.data_prep.lance_writer import lance_storage_options, write_cleaned_to_lance

@dataclass(frozen=True)
class PrepareRequest:
    tar_dir: str
    work_dir: str
    bucket: str
    enterprise_id: str
    group_id: str
    dataset: str
    np: int
    oss_endpoint: str
    access_key: str
    secret_key: str
    session_token: str | None = None
    region: str = "cn-hangzhou"

def _run_dj(recipe_path: str, log_path: str) -> int:
    """DJ 经外部 venv 子进程(spike 教训:Ray 禁瞬态 uv 环境)。DJ_BIN 指 dj-process。"""
    dj = os.getenv("DJ_BIN", "dj-process")
    with open(log_path, "w") as log:
        return subprocess.run([dj, "--config", recipe_path], stdout=log, stderr=log,
                              env={**os.environ, "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"},
                              ).returncode

def _audit(audit: AuditWriter, ctx: Context, req: PrepareRequest, action: str,
           decision: str, reason: str = "") -> None:
    audit.write(AuditEvent(
        ts=datetime.now(timezone.utc).isoformat(), enterprise_id=req.enterprise_id,
        group_id=req.group_id, actor_user=ctx.user,
        actor_role=ctx.role_in(EnterpriseId(req.enterprise_id), GroupId(req.group_id)) or "none",
        action=action, resource_uri=f"dataset/{req.dataset}", decision=decision,
        override=False, reason=reason, metadata={}))

def run_prepare(ctx: Context, req: PrepareRequest, audit: AuditWriter, *,
                convert_fn=wds_to_jsonl, dj_fn=_run_dj, lance_fn=write_cleaned_to_lance) -> dict:
    """一次数据准备:can() 唯一出入口 → 转换 → DJ(Ray)→ Lance on OSS → 审计。"""
    resource = Resource(kind="dataset", enterprise_id=EnterpriseId(req.enterprise_id),
                        group_id=GroupId(req.group_id))
    d = can(ctx, "data.prepare", resource)
    _audit(audit, ctx, req, "data.prepare", "allow" if d.allow else "deny", d.reason)
    if not d.allow:
        raise PermissionError(d.reason)

    paths = DatasetPaths(bucket=req.bucket, enterprise_id=EnterpriseId(req.enterprise_id),
                         group_id=GroupId(req.group_id), dataset=req.dataset)
    work = Path(req.work_dir); work.mkdir(parents=True, exist_ok=True)
    jsonl_dir, cleaned_dir = work / "in", work / "out"

    n_in = convert_fn(req.tar_dir, str(jsonl_dir))
    recipe_path = work / "recipe.yaml"
    recipe_path.write_text(build_recipe(str(jsonl_dir / "data.jsonl"), str(cleaned_dir), req.np))
    rc = dj_fn(str(recipe_path), str(work / "dj.log"))
    if rc != 0:
        _audit(audit, ctx, req, "data.prepare.failed", "allow", f"dj exit={rc}")
        raise RuntimeError(f"data-juicer failed (exit={rc}), log: {work / 'dj.log'}")

    opts = lance_storage_options(req.oss_endpoint, req.bucket, req.access_key,
                                 req.secret_key, req.session_token, req.region)
    n_out = lance_fn(str(cleaned_dir / "cleaned.jsonl"), paths.processed_uri, opts, req.oss_endpoint)
    return {"rows_in": n_in, "rows_written": n_out, "lance_uri": paths.processed_uri}
