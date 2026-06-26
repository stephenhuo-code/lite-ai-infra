# services/gateway/bff/workspace_store.py
# workspace 目录 = OSS 路径 <企业>/{owner}/workspace/<ws>/(owner 隔离,owner 模型 ADR-024)。
# ws 名禁路径穿越防越界他人前缀。hydrate/persist = 会话开/关时 OSS↔工作目录同步(注入式
# syncer:真实 syncer 形态待 Task0 探针,此处为纯逻辑可单测)。
from __future__ import annotations

import re

_WS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def workspace_prefix(*, enterprise: str, owner: str, ws: str) -> str:
    if not _WS_RE.match(ws):
        raise ValueError(f"invalid workspace name: {ws!r}")
    return f"{enterprise}/{owner}/workspace/{ws}/"


def hydrate(oss, fs, *, prefix: str) -> int:
    """OSS → 工作目录(会话开:水合)。返回拷贝文件数。"""
    n = 0
    for key in oss.list(prefix):
        rel = key[len(prefix):]
        if rel:
            fs.write(rel, oss.get(key))
            n += 1
    return n


def persist(oss, fs, *, prefix: str) -> int:
    """工作目录 → OSS(会话关:持久化)。返回写回文件数。"""
    n = 0
    for rel in fs.listrel():
        oss.put_object(prefix + rel, fs.read(rel))
        n += 1
    return n
