# libs/identity/ids.py
"""标识类型(宪法 §1.2):EnterpriseId / GroupId 是独立类型,不与裸 str 互转。

NewType 提供静态层面的不可互换(mypy 下裸 str 传参会报错);运行时零开销。
静态强制门禁(mypy in CI)是 S1 跟进项——见 code review 2026-06-10 #4。
"""
from __future__ import annotations
from typing import NewType

EnterpriseId = NewType("EnterpriseId", str)   # e-XXXX,全局唯一
GroupId = NewType("GroupId", str)             # g-XXXX,企业内唯一
