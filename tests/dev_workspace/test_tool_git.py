from services.dev_workspace_mcp.tools.git import git_commit, parse_status


class FakeRunner:
    def __init__(self, out=""):
        self.out = out
        self.ran = []

    def run(self, argv, cwd):
        self.ran.append((argv, cwd))
        return self.out


def test_status_parses_porcelain():
    st = parse_status(" M recipe.py\n?? output/\n")
    assert st == [{"x": "M", "path": "recipe.py"}, {"x": "?", "path": "output/"}]


def test_commit_runs_add_and_commit_local_only():
    r = FakeRunner("")
    git_commit(r, cwd="/ws", message="feat: x")
    cmds = [a for a, _ in r.ran]
    assert ["git", "add", "-A"] in cmds
    assert any(c[:2] == ["git", "commit"] and "feat: x" in c for c in cmds)
    assert not any("push" in c for c in cmds)     # 本地 only,绝不 push
