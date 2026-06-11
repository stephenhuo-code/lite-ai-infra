# libs/audit/oss_audit.py
from __future__ import annotations
import json, logging, uuid
from dataclasses import dataclass, asdict
from typing import Protocol

log = logging.getLogger("audit")

@dataclass(frozen=True)
class AuditEvent:
    ts: str
    enterprise_id: str
    group_id: str | None
    actor_user: str
    actor_role: str
    action: str
    resource_uri: str
    decision: str          # allow | deny
    override: bool
    reason: str
    metadata: dict

def _audit_key(ev: AuditEvent) -> str:
    y, m, d = ev.ts[0:4], ev.ts[5:7], ev.ts[8:10]
    return f"audit/{y}/{m}/{d}/{ev.ts}-{uuid.uuid4().hex[:8]}.jsonl"

def addressing_style(endpoint: str, explicit: str | None = None) -> str:
    """对象存储寻址方式:MinIO 要 path-style;真阿里云 OSS 拒绝 path-style
    (SecondLevelDomainForbidden,Spike C 2026-06-11 实测)→ 按 endpoint 自适应;
    explicit(如 env OSS_ADDRESSING_STYLE)可显式覆盖。"""
    if explicit:
        return explicit
    return "virtual" if "aliyuncs.com" in endpoint else "path"


class AuditSink(Protocol):
    def put(self, key: str, body: bytes) -> None: ...

class OssAuditSink:
    """真实现：boto3 S3 client —— 本地 MinIO / 阿里云 OSS（S3 兼容 endpoint）。"""
    def __init__(self, bucket: str, client):
        self._bucket = bucket
        self._s3 = client
    def put(self, key: str, body: bytes) -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=body)

class AuditWriter:
    """追加写审计；尽力写（ADR-010/013）：sink 失败仅记日志、绝不抛给调用方。"""
    def __init__(self, sink: AuditSink):
        self._sink = sink
    def write(self, ev: AuditEvent) -> str | None:
        key = _audit_key(ev)
        try:
            self._sink.put(key, json.dumps(asdict(ev)).encode())
            return key
        except Exception:
            log.exception("audit write failed (best-effort, dropped): %s", ev.action)
            return None
