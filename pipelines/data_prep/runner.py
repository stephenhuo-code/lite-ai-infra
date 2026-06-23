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
from pipelines.data_prep.oss_fetch import fetch_oss_tars, build_s3

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
    process: list[dict] | None = None   # Layer 1 DJ 算子自定义;None → build_recipe 用默认集
    source_location: str | None = None  # catalog-driven:OSS 前缀 s3://{bucket}/{eid}/{gid}/raw/{ds}/;给定则从 OSS 取(优先于 tar_dir),否则用本地 tar_dir(旧行为)

def _run_dj(recipe_path: str, log_path: str) -> int:
    """DJ 经外部 venv 子进程(spike 教训:Ray 禁瞬态 uv 环境)。DJ_BIN 指 dj-process。
    关键(2026-06-15 实测):服务由 `uv run` 起,子进程会继承 uv-run 上下文(UV_*、
    VIRTUAL_ENV=主 .venv)。Ray 据此按 uv 模式起 worker → 在 cwd 重建主 .venv(无 ray)
    → ModuleNotFoundError: ray → 卡死。故剥掉 UV_*,并把 VIRTUAL_ENV/PATH 指向 DJ venv,
    让 Ray worker 用含 ray 的 .dj-venv。"""
    dj = os.getenv("DJ_BIN", "dj-process")
    env = {k: v for k, v in os.environ.items() if not k.startswith("UV_")}
    # 关掉新版 Ray 的 "uv run" worker 模式:否则它在 uv 项目里用 `uv run` 起 worker,
    # uv 永远绑主 .venv(无 ray)→ worker ImportError ray(2026-06-15 实测)。
    env.update(HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1", RAY_ENABLE_UV_RUN_RUNTIME_ENV="0")
    # 把 VIRTUAL_ENV/PATH 指向 DJ venv(解软链 + 校验确是 venv);识别不了(如默认裸 dj-process)
    # 就**清掉**继承来的 VIRTUAL_ENV —— 否则它仍指主 .venv(无 ray),Ray worker 照样崩。
    venv = None
    if os.sep in dj or Path(dj).is_absolute():
        real = Path(dj).resolve()
        if real.parent.name == "bin" and any((real.parent / p).exists() for p in ("python", "python3")):
            venv = real.parent.parent
    if venv:
        env["VIRTUAL_ENV"] = str(venv)
        env["PATH"] = f"{venv / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    else:
        env.pop("VIRTUAL_ENV", None)
    with open(log_path, "w") as log:
        return subprocess.run([dj, "--config", recipe_path], stdout=log, stderr=log, env=env).returncode

def _audit(audit: AuditWriter, ctx: Context, req: PrepareRequest, action: str,
           decision: str, reason: str = "") -> None:
    audit.write(AuditEvent(
        ts=datetime.now(timezone.utc).isoformat(), enterprise_id=req.enterprise_id,
        group_id=req.group_id, actor_user=ctx.user,
        actor_role=ctx.role_in(EnterpriseId(req.enterprise_id), GroupId(req.group_id)) or "none",
        action=action, resource_uri=f"dataset/{req.dataset}", decision=decision,
        override=False, reason=reason, metadata={}))

def run_prepare(ctx: Context, req: PrepareRequest, audit: AuditWriter, *,
                convert_fn=wds_to_jsonl, dj_fn=_run_dj, lance_fn=write_cleaned_to_lance,
                fetch_fn=fetch_oss_tars, build_s3_fn=build_s3) -> dict:
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

    src_dir = req.tar_dir
    if req.source_location:                        # catalog-driven:从 OSS 前缀取 tar 到本地
        src_dir = str(Path(req.work_dir) / "tars")
        # source_location 形如 s3://bucket/eid/gid/raw/ds/ → 拆出 bucket 与 key 前缀
        rest = req.source_location.removeprefix("s3://")
        b, _, key_prefix = rest.partition("/")
        s3 = build_s3_fn(req.oss_endpoint, req.access_key, req.secret_key, req.session_token, req.region)
        n_tar = fetch_fn(s3, bucket=b, prefix=key_prefix, dest_dir=src_dir)
        if n_tar == 0:
            raise RuntimeError(f"no .tar under {req.source_location}")
    n_in = convert_fn(src_dir, str(jsonl_dir))
    recipe_path = work / "recipe.yaml"
    recipe_path.write_text(build_recipe(str(jsonl_dir / "data.jsonl"), str(cleaned_dir), req.np,
                                        process=req.process))
    rc = dj_fn(str(recipe_path), str(work / "dj.log"))
    if rc != 0:
        _audit(audit, ctx, req, "data.prepare.failed", "allow", f"dj exit={rc}")
        raise RuntimeError(f"data-juicer failed (exit={rc}), log: {work / 'dj.log'}")

    opts = lance_storage_options(req.oss_endpoint, req.bucket, req.access_key,
                                 req.secret_key, req.session_token, req.region)
    n_out = lance_fn(str(cleaned_dir / "cleaned.jsonl"), paths.processed_uri, opts, req.oss_endpoint)
    return {"rows_in": n_in, "rows_written": n_out, "lance_uri": paths.processed_uri}
