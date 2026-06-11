# spikes/cerbos_seam/spike_b.py
"""
Spike B —— Cerbos can() seam(ADR-011)。

验证:**同一** `can(ctx, action, resource)` 签名能改调 Cerbos PDP,
复现 AC-1(owner 删自己的 job → allow)/ AC-2(非 owner → deny)/
AC-6(跨企业读 → deny),与 v1 薄引擎逐条一致;且 `services/gateway/app.py`
零改(它 import 的是 `libs.authz.engine.can` —— v2 只需替换 engine 内部实现)。

跑:
  docker run --rm -d --name cerbos-spike -p 3592:3592 \
    -v $PWD/spikes/cerbos_seam/policies:/policies ghcr.io/cerbos/cerbos:latest server
  uv run python spikes/cerbos_seam/spike_b.py
结论回写 ADR-011。
"""
from __future__ import annotations
import httpx

from libs.identity.context import Context, parse_context
from libs.authz.types import Resource, Decision
from libs.authz import engine as v1_engine

CERBOS = "http://localhost:3592"


def cerbos_can(ctx: Context, action: str, resource: Resource) -> Decision:
    """与 libs.authz.engine.can **同签名** 的 Cerbos 实现(v2 候选)。"""
    payload = {
        "requestId": "spike-b",
        "principal": {
            "id": ctx.user,
            "roles": ["user"],
            "attr": {"memberships": [
                {"enterprise_id": m.enterprise_id, "group_id": m.group_id, "role": m.role}
                for m in ctx.memberships
            ]},
        },
        "resources": [{
            "resource": {
                "kind": resource.kind, "id": "r-1",
                "attr": {"enterprise_id": resource.enterprise_id,
                         "group_id": resource.group_id,
                         "owner": resource.owner},
            },
            "actions": [action],
        }],
    }
    r = httpx.post(f"{CERBOS}/api/check/resources", json=payload, timeout=5)
    r.raise_for_status()
    effect = r.json()["results"][0]["actions"][action]
    return Decision(allow=(effect == "EFFECT_ALLOW"),
                    reason="" if effect == "EFFECT_ALLOW" else f"cerbos:{effect}")


CASES = [
    # (名称, ctx, action, resource, 期望 allow)
    ("AC-1 owner 删自己的 running job",
     parse_context("u-alice", ["/e-0001/g-0001/members"]), "job.delete",
     Resource(kind="job", enterprise_id="e-0001", group_id="g-0001", owner="u-alice"), True),
    ("AC-2 非 owner member 删别人 job",
     parse_context("u-alice", ["/e-0001/g-0001/members"]), "job.delete",
     Resource(kind="job", enterprise_id="e-0001", group_id="g-0001", owner="u-bob"), False),
    ("AC-6 跨企业 dataset.read",
     parse_context("u-alice", ["/e-0001/g-0001/members"]), "dataset.read",
     Resource(kind="dataset", enterprise_id="e-0099"), False),
    ("AC-9 group-admin 删组员 job",
     parse_context("u-lead", ["/e-0001/g-0001/admins"]), "job.delete",
     Resource(kind="job", enterprise_id="e-0001", group_id="g-0001", owner="u-bob"), True),
]


def main():
    print(f"{'case':<34}{'v1 engine':>10}{'cerbos':>8}{'expect':>8}  verdict")
    print("-" * 70)
    all_ok = True
    for name, ctx, action, res, expect in CASES:
        v1 = v1_engine.can(ctx, action, res).allow
        cb = cerbos_can(ctx, action, res).allow
        ok = (v1 == cb == expect)
        all_ok &= ok
        print(f"{name:<34}{str(v1):>10}{str(cb):>8}{str(expect):>8}  {'PASS ✓' if ok else 'FAIL ✗'}")
    assert all_ok, "存在不一致"
    print("\nSpike B PASS:同一 can() 签名调 Cerbos,与 v1 薄引擎逐条一致。")
    print("app.py 零改证明:gateway 只 import libs.authz.engine.can —— v2 swap 仅替换 engine 内部。")


if __name__ == "__main__":
    main()
