from __future__ import annotations
import json, os, shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

_PUBLIC = ("size", "error")   # status.json 上的可投影字段(spec 之外的运行期字段)

@dataclass(frozen=True)
class RawSpec:
    raw_id: str
    name: str
    owner_user: str            # owner 模型(ADR-024):上传用户(=sub,§1.4 不透明);取代 group_id
    enterprise_id: str
    sub: str
    oss_key: str               # 服务端构造、校验过的完整 OSS key(隔离写死)
    upload_id: str | None = None   # multipart 时的 OSS UploadId

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class RawDatasetStore:
    """状态文件原始数据集存储(ADR-018:v1 无 PG;镜像 JobStore)。spec.json 写一次;
    status.json 走 temp + os.replace 原子替换 —— service 写 pending→ready/failed、
    GC 写删除,读者(list_raw)永不见半写文件。"""
    def __init__(self, root: str):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def raw_dir(self, raw_id: str) -> Path:
        return self.root / raw_id

    def create(self, spec: RawSpec) -> None:
        d = self.raw_dir(spec.raw_id); d.mkdir(parents=True, exist_ok=True)
        (d / "spec.json").write_text(json.dumps(asdict(spec)))
        ts = _now()
        self._write_status(spec.raw_id, {"status": "pending", "created_at": ts, "updated_at": ts,
                                         **{k: None for k in _PUBLIC}})

    def _write_status(self, raw_id: str, status_obj: dict) -> None:
        d = self.raw_dir(raw_id)
        tmp = d / f".status.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(status_obj))
        os.replace(tmp, d / "status.json")

    def update(self, raw_id: str, status: str, **fields) -> None:
        p = self.raw_dir(raw_id) / "status.json"
        cur = json.loads(p.read_text()) if p.exists() else {"created_at": _now(), **{k: None for k in _PUBLIC}}
        cur.update(status=status, updated_at=_now(), **fields)
        self._write_status(raw_id, cur)

    def load_spec(self, raw_id: str) -> RawSpec | None:
        p = self.raw_dir(raw_id) / "spec.json"
        return RawSpec(**json.loads(p.read_text())) if p.exists() else None

    def read(self, raw_id: str) -> dict | None:
        d = self.raw_dir(raw_id)
        if not (d / "status.json").exists():
            return None
        sp = d / "spec.json"
        spec = json.loads(sp.read_text()) if sp.exists() else {}
        st = json.loads((d / "status.json").read_text())
        return {"id": raw_id, "name": spec.get("name"), "owner_user": spec.get("owner_user"),
                "enterprise_id": spec.get("enterprise_id"), "oss_key": spec.get("oss_key"),
                "status": st["status"], "created_at": st["created_at"], "updated_at": st["updated_at"],
                **{k: st.get(k) for k in _PUBLIC}}

    def list_raw(self) -> list[dict]:
        """纯取数,不授权(授权/过滤在 handler):投影含 enterprise_id/owner_user 供 can() 过滤。
        按 created_at 倒序。登记:扫目录 O(n),量大需索引(vN+,S2a 真 store)。"""
        out: list[dict] = []
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            r = self.read(d.name)
            if r is not None:
                out.append(r)
        out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return out

    def delete(self, raw_id: str) -> None:
        shutil.rmtree(self.raw_dir(raw_id), ignore_errors=True)
