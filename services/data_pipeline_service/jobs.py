from __future__ import annotations
import json, os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

_PUBLIC = ("rows_in", "rows_written", "lance_uri", "error")

@dataclass(frozen=True)
class JobSpec:
    job_id: str
    dataset: str
    group_id: str
    enterprise_id: str
    role: str            # 提交时调用者在该组的角色快照(worker 复检 can() 用)
    sub: str
    source_location: str  # S2a catalog-driven:源 raw 数据集 OSS 前缀(submit 时带 bearer 经 metadata 解析;worker detached 无 bearer 故 submit 时定)
    np: int
    process: list[dict] | None = None

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class JobStore:
    """状态文件作业存储(ADR-018:v1 无 PG)。spec.json 写一次。status.json 按生命周期
    阶段单写者:service 进程写 queued→running 及看门狗的 running→failed;detached worker
    进程写 running→终态。二者属**不同进程**,理论上可同时落在同一 status.json 上,故
    `_write_status` 走 **temp + os.replace 原子替换** —— 任一读者(看门狗 running_jobs)
    永不会读到半写文件(否则 json.loads 抛错使 dispatch 崩)。看门狗只回收
    status=='running' 且 pid 已死的作业:worker 写终态后 status 即非 running,不会被误杀
    (worker 进程在执行 update 期间其 pid 仍活,看门狗据 pid_alive 跳过)。"""
    def __init__(self, root: str):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def create(self, spec: JobSpec) -> None:
        d = self.job_dir(spec.job_id); d.mkdir(parents=True, exist_ok=True)
        (d / "spec.json").write_text(json.dumps(asdict(spec)))
        ts = _now()
        self._write_status(spec.job_id, {"status": "queued", "created_at": ts, "updated_at": ts,
                                         **{k: None for k in _PUBLIC}})

    def _write_status(self, job_id: str, status_obj: dict) -> None:
        # 原子替换:跨进程(service 看门狗 / detached worker)写同一 status.json 时,
        # 读者永不见半写文件(POSIX rename 原子)。temp 与目标同目录确保同一文件系统。
        d = self.job_dir(job_id)
        tmp = d / f".status.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(status_obj))
        os.replace(tmp, d / "status.json")

    def update(self, job_id: str, status: str, **fields) -> None:
        p = self.job_dir(job_id) / "status.json"
        # status.json 缺失(损坏 job dir)时从最小基底起,保证终态写入仍成功(read 投影需 created_at)
        cur = json.loads(p.read_text()) if p.exists() else {"created_at": _now(), **{k: None for k in _PUBLIC}}
        cur.update(status=status, updated_at=_now(), **fields)
        self._write_status(job_id, cur)

    def load_spec(self, job_id: str) -> JobSpec | None:
        p = self.job_dir(job_id) / "spec.json"
        return JobSpec(**json.loads(p.read_text())) if p.exists() else None

    def read(self, job_id: str) -> dict | None:
        d = self.job_dir(job_id)
        if not (d / "status.json").exists():
            return None
        sp = d / "spec.json"
        spec = json.loads(sp.read_text()) if sp.exists() else {}   # 损坏 job:spec 缺失仍可投影终态而非 500
        st = json.loads((d / "status.json").read_text())
        return {"id": job_id, "dataset": spec.get("dataset"), "group_id": spec.get("group_id"),
                "enterprise_id": spec.get("enterprise_id"), "status": st["status"],
                "terminal": st["status"] in ("succeeded", "failed"),   # 派生:客户端按此判终态(ADR-018 不变量 4)
                "created_at": st["created_at"], "updated_at": st["updated_at"],
                **{k: st.get(k) for k in _PUBLIC}}

    def list_jobs(self) -> list[dict]:
        """**纯取数,不做授权**:遍历目录 → 对每个 job `read()` 投影(含 enterprise_id/group_id ——
        这两字段在 spec.json,`_all_status()` 只读 status.json 拿不到,故**必须用 read()**,否则
        handler 无法 can() 按企业/组过滤 → 隔离失效)。按 created_at 倒序。授权/过滤在 handler。
        I-2:spec.json 缺失的损坏 job,read() 投影出 enterprise_id=None,handler fail-closed 排除。
        登记:扫目录 O(n);作业量上千需索引(vN+;S2a 真 store 落地时换 DB 查询)。"""
        out: list[dict] = []
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            j = self.read(d.name)
            if j is not None:
                out.append(j)
        out.sort(key=lambda j: j.get("created_at") or "", reverse=True)
        return out

    def _all_status(self):
        for d in self.root.iterdir():
            sp = d / "status.json"
            if sp.exists():
                yield d.name, json.loads(sp.read_text())

    def running_count(self) -> int:
        return sum(1 for _, st in self._all_status() if st["status"] == "running")

    def running_jobs(self) -> list[tuple[str, int | None]]:
        """(job_id, pid) of status==running —— 供 PID 看门狗回收孤儿(ADR-018)。"""
        return [(jid, st.get("pid")) for jid, st in self._all_status() if st["status"] == "running"]

    def oldest_queued(self) -> str | None:
        q = [(st["created_at"], jid) for jid, st in self._all_status() if st["status"] == "queued"]
        return min(q)[1] if q else None
