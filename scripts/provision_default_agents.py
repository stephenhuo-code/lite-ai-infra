#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from services.gateway.bff.omnigent_proxy import ensure_default_agents_for_enterprise


def _fmt(items: list[str]) -> str:
    return ", ".join(items) if items else "none"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision default enterprise agents")
    parser.add_argument("--enterprise", required=True, help="KC organization alias, e.g. ent-demo")
    parser.add_argument(
        "--omni-base-url",
        default=os.getenv("OMNIGENT_BASE_URL", "http://127.0.0.1:8900"),
    )
    parser.add_argument(
        "--identity-email",
        default=os.getenv("OMNIGENT_IDENTITY_EMAIL", "system@lite-ai.local"),
    )
    args = parser.parse_args(argv)

    result = ensure_default_agents_for_enterprise(
        args.enterprise,
        omni_base_url=args.omni_base_url,
        identity_email=args.identity_email,
    )
    print(f"default agents for `{args.enterprise}` ready")
    print(f"  created: {_fmt(result.created)}")
    print(f"  skipped: {_fmt(result.skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
