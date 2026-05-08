# Spec-Kit + Superpowers 多人协作工作流指南

> 通用工作流指导文档。适用于多人 / 多 agent 协作的工程项目，需要统一需求、架构、任务拆解，并保证实施质量的场景。

---

## 一、工具分工

| 维度 | spec-kit | Superpowers |
|---|---|---|
| 解决什么 | **做对的事**（对齐需求、架构、任务） | **把事做对**（实施质量、验证、调试） |
| 产物 | 版本化文档（spec / plan / tasks） | 工作流约束（TDD、verification、review） |
| 协作角色 | 团队契约层 | 个人 / agent 实施层 |
| 是否进仓库 | 是（`specs/`、`memory/constitution.md`） | 否（只是流程约束） |

**核心原则**：规划与对齐**只用 spec-kit**，实施与质量门**只用 Superpowers**，不要让两套工具重复做同一件事。

---

## 二、完整流程图

```
┌─────────────────────────────────────────────────────────────┐
│                  探索阶段（按需启用）                       │
│                                                             │
│   superpowers:brainstorming                                 │
│      └─ 需求模糊时使用：挖透用户、场景、边界、成功标准      │
│         产物只进脑子，不进仓库；输出喂给下一步 /specify     │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│              对齐阶段（spec-kit 主导）                       │
│                                                             │
│   /constitution   ── 项目宪法（首次或重大原则变更时）       │
│        ↓                                                    │
│   /specify        ── 用户故事 + 验收标准                    │
│        ↓                                                    │
│   /clarify (可选) ── 澄清歧义                               │
│        ↓                                                    │
│   /plan           ── 架构 + 技术选型 + 数据模型 + 契约      │
│        ↓                                                    │
│   /tasks          ── 可执行任务清单（含 [P] 并行标记）      │
│        ↓                                                    │
│   /analyze (可选) ── 自动审计 spec / plan / tasks 一致性    │
│                                                             │
│   ◀── 文档先于代码 PR：团队 review 的是 spec/plan/tasks ──▶ │
├─────────────────────────────────────────────────────────────┤
│              实施阶段（Superpowers 主导）                    │
│                                                             │
│   /implement                                                │
│        │                                                    │
│        ├─ superpowers:using-git-worktrees                   │
│        │     工作区隔离（多人 / 多 agent 并行时）           │
│        │                                                    │
│        ├─ superpowers:test-driven-development               │
│        │     红 → 绿 → 重构，测试先行                       │
│        │                                                    │
│        ├─ superpowers:dispatching-parallel-agents           │
│        │     [P] 任务派给多个子 agent                       │
│        │                                                    │
│        ├─ superpowers:systematic-debugging                  │
│        │     遇 bug 时系统化定位，禁止瞎猜补丁              │
│        │                                                    │
│        ├─ superpowers:verification-before-completion        │
│        │     提交前必须跑命令拿证据                         │
│        │                                                    │
│        └─ superpowers:requesting-code-review                │
│              PR 前让另一个 agent 互审                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**关于 brainstorming 的位置**：它是 `/specify` 的"上游漏斗"。需求模糊时必用，需求清晰时（小迭代、已对齐过的需求）跳过。它的产物不进仓库，只为下一步 `/specify` 提供高质量输入。

---

## 三、最简工作流建议（细化到执行命令）

### 0. 一次性环境准备

```bash
# 安装 spec-kit CLI
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git

# 在项目根目录初始化（生成 .specify/、memory/constitution.md、specs/）
cd <项目根目录>
specify init . --ai claude
```

确认 Superpowers 插件已装（在 Claude Code 中）：

```
/plugin
# 列表中应出现 superpowers:* 系列 skill
```

### 1. 项目首次：写宪法

```
/constitution
```
回答提示，固化项目原则（如"必须 TDD"、"PR 必须链接 spec"）。提交 `memory/constitution.md`。

### 2. 每个 feature：探索（可选）

需求模糊时执行；清晰则跳过：

```
/skill superpowers:brainstorming
```

### 3. 每个 feature：对齐

```
/specify           # 写 spec.md
/clarify           # 可选，澄清歧义
/plan              # 出架构、契约、数据模型
/tasks             # 拆成可执行任务，标 [P] 并行项
/analyze           # 可选，审计三层文档一致性
```

提交"文档 PR"，团队 review `specs/NNN-xxx/` 下的产物，**先于任何代码合入**。

### 4. 每个任务：实施

进入隔离工作区（多人并行时）：

```
/skill superpowers:using-git-worktrees
```

按 `tasks.md` 取任务后执行：

```
/skill superpowers:test-driven-development
# 红 → 绿 → 重构，每个任务都先写测试

# 多个 [P] 任务同时推进
/skill superpowers:dispatching-parallel-agents

# 实施中遇 bug
/skill superpowers:systematic-debugging
```

### 5. 提交前：质量门

```
/skill superpowers:verification-before-completion
# 跑测试、lint、build 等命令，输出证据，禁止口头"完成"

/skill superpowers:requesting-code-review
# 让另一个 agent / 同事审查
```

PR 描述里链接 `specs/NNN-xxx/`，合入后用：

```
/skill superpowers:finishing-a-development-branch
```

### 一行命令速查

| 阶段 | 命令 |
|---|---|
| 装 spec-kit | `uv tool install specify-cli --from git+https://github.com/github/spec-kit.git` |
| 初始化 | `specify init . --ai claude` |
| 项目宪法 | `/constitution` |
| 探索（按需） | `/skill superpowers:brainstorming` |
| 对齐 | `/specify` → `/clarify` → `/plan` → `/tasks` → `/analyze` |
| 隔离 | `/skill superpowers:using-git-worktrees` |
| 实施 | `/skill superpowers:test-driven-development` |
| 并行 | `/skill superpowers:dispatching-parallel-agents` |
| 调试 | `/skill superpowers:systematic-debugging` |
| 验证 | `/skill superpowers:verification-before-completion` |
| 互审 | `/skill superpowers:requesting-code-review` |
| 收尾 | `/skill superpowers:finishing-a-development-branch` |

---

## 四、团队约定（建议写进 constitution.md）

1. 未经 `/specify` 的功能**不允许直接写代码**——避免方向跑偏。
2. 架构决策必须经过 `/plan`——技术选型留痕、可追溯。
3. 任务必须从 `/tasks` 产出——禁止口头分工。
4. 实施必须用 TDD（`superpowers:test-driven-development`）。
5. 提交前必跑 `verification-before-completion`——禁止口头"完成"，要证据。
6. PR 必须链接 `specs/NNN-xxx/`——审查者能回溯需求源头。

---

## 五、常见误区

| 误区 | 正确做法 |
|---|---|
| 用 `superpowers:writing-plans` 又用 `/plan` | 规划只用 spec-kit |
| 用 brainstorming 后跳过 `/specify` | 团队拿不到统一文档，必须落成 spec |
| 跳过 `/constitution` 直接 `/specify` | 缺项目硬约束，AI 生成会飘 |
| 直接写代码再补 spec | spec 沦为八股，失去对齐价值 |
| 提交时口头说"测试通过了" | 必须 `verification-before-completion` 跑命令 |

---

## 六、单 feature 标准动作清单

**负责人：**
- [ ] 需求模糊时跑 `superpowers:brainstorming` 挖透
- [ ] `/specify` 写 spec.md
- [ ] `/clarify` 澄清歧义（可选）
- [ ] `/plan` 出架构 + 契约
- [ ] `/tasks` 拆任务（识别 `[P]` 并行项）
- [ ] 提交"文档 PR"让团队 review

**实施者（人 / agent）：**
- [ ] 拉 `tasks.md`，必要时 `using-git-worktrees` 开隔离工作区
- [ ] `test-driven-development` 实施每个任务
- [ ] 并行任务用 `dispatching-parallel-agents`
- [ ] 遇 bug 用 `systematic-debugging`
- [ ] 完成前 `verification-before-completion`
- [ ] PR 前 `requesting-code-review`
- [ ] PR 链接 `specs/NNN-xxx/`

---

## 七、一句话总结

> **spec-kit 让团队对齐"做什么"，Superpowers 让 AI 实施"做对"。前者是契约，后者是质量门，两者串起来才是多人协作下的完整工作流。**
