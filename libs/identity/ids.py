# libs/identity/ids.py
"""标识类型(宪法 §1.2):EnterpriseId 是独立类型,不与裸 str 互转。

NewType 提供静态层面的不可互换(mypy 下裸 str 传参会报错);运行时零开销。
静态强制门禁(mypy in CI)是 S1 跟进项——见 code review 2026-06-10 #4。

身份降两级后(ADR-025)已无用户组层 → GroupId 删除;enterprise_id = KC Organization
的不透明 alias(token organization claim 携带,见 spike RESULTS F1)。
"""
from __future__ import annotations
from typing import NewType

EnterpriseId = NewType("EnterpriseId", str)   # KC Organization 不透明 alias,全局唯一
