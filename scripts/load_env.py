#!/usr/bin/env python3
"""桥接:把 configs/<LITEAI_ENV>.yaml 摊平成某服务的 env,打印供 shell 消费。
用法:
  load_env.py <service>            # 打印 'K=V K=V'(供 `env $(load_env.py svc)`)
  load_env.py <service> --export   # 打印 'export K=V'(供 `eval`)
env 取 $LITEAI_ENV(再缺省 $ENV,再缺省 local)。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 仓库根入 path(直接跑)

from libs.config import export_env, load_settings, ConfigError


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: load_env.py <service> [--export]", file=sys.stderr)
        return 2
    service = argv[0]
    as_export = "--export" in argv[1:]
    env = os.environ.get("LITEAI_ENV") or os.environ.get("ENV") or "local"
    try:
        flat = export_env(load_settings(env), service)
    except ConfigError as e:
        print(f"load_env: {e}", file=sys.stderr)
        return 1
    prefix = "export " if as_export else ""
    print(" ".join(f"{prefix}{k}={v}" for k, v in flat.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
