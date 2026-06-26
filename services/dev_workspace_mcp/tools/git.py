# services/dev_workspace_mcp/tools/git.py
# 本地 git(status/log/commit);绝不 push(远端 git 用户自配,spec 推迟)。
# runner 注入(沙箱内执行 git);纯解析可单测。
from __future__ import annotations


def parse_status(porcelain: str) -> list[dict]:
    out = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        out.append({"x": line[:2].strip()[:1] or "?", "path": line[3:].strip() or line[2:].strip()})
    return out


def git_status(runner, *, cwd: str) -> list[dict]:
    return parse_status(runner.run(["git", "status", "--porcelain"], cwd=cwd))


def git_log(runner, *, cwd: str, n: int = 20) -> str:
    return runner.run(["git", "log", f"-{n}", "--oneline"], cwd=cwd)


def git_commit(runner, *, cwd: str, message: str) -> None:
    runner.run(["git", "add", "-A"], cwd=cwd)
    runner.run(["git", "commit", "-m", message], cwd=cwd)   # 本地;无 push
