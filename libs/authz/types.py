# libs/authz/types.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Resource:
    kind: str                  # "job" | "dataset" | "pipeline" | ...
    enterprise_id: str
    group_id: str | None = None
    scope: str = "private"     # "private" | "shared"
    owner: str | None = None
    attrs: dict | None = None  # 例：{"gpu": 8, "state": "running"}

@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""
