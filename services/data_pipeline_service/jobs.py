from __future__ import annotations
import json
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
    tar_dir: str
    np: int
    process: list[dict] | None = None

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class JobStore:
    """状态文件作业存储(ADR-018:v1 无 PG)。spec.json 写一次;status.json 由
    service(queued→running)与 worker(running→终态)分时写,无并发写者。"""
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
        (self.job_dir(job_id) / "status.json").write_text(json.dumps(status_obj))

    def update(self, job_id: str, status: str, **fields) -> None:
        cur = json.loads((self.job_dir(job_id) / "status.json").read_text())
        cur.update(status=status, updated_at=_now(), **fields)
        self._write_status(job_id, cur)

    def load_spec(self, job_id: str) -> JobSpec | None:
        p = self.job_dir(job_id) / "spec.json"
        return JobSpec(**json.loads(p.read_text())) if p.exists() else None

    def read(self, job_id: str) -> dict | None:
        d = self.job_dir(job_id)
        if not (d / "status.json").exists():
            return None
        spec = json.loads((d / "spec.json").read_text())
        st = json.loads((d / "status.json").read_text())
        return {"id": job_id, "dataset": spec["dataset"], "group_id": spec["group_id"],
                "enterprise_id": spec["enterprise_id"], "status": st["status"],
                "terminal": st["status"] in ("succeeded", "failed"),   # 派生:客户端按此判终态(ADR-018 不变量 4)
                "created_at": st["created_at"], "updated_at": st["updated_at"],
                **{k: st.get(k) for k in _PUBLIC}}

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
