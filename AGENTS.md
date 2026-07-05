# 架构宪法（必读·不可违反）

**开始任何编码 / 计划 / 评审前，ALWAYS 先读并遵守 [`docs/constitution.md`](docs/constitution.md)。** 它是本项目的硬纪律（多企业租户与标识、身份与授权、微服务 + API 优先、审计与数据、版本路线、CI 防线），来源为 ADR-002/010/011/012/024/025 + design spec。**多企业租户与标识（ADR-025）：企业 = KC Organization 的不透明 alias，身份降两级（平台→企业→用户，v1 移除用户组层），企业归属随 token 的 `organization` claim；自助注册按邮箱域自动归企业 + 邀请；用户组 / per-group 授权 = vN+（Cerbos）。** 与具体实现冲突时以宪法为准；宪法变更必须走 ADR。

详细设计见 `docs/superpowers/specs/2026-05-08-llm-infra-platform-design.md` 与 `docs/adr/`。

---

# Codex 项目入口

本文件是 Codex 在本仓库工作的主入口。Claude 历史上下文仍保留在 `CLAUDE.md` / `.claude/` 供追溯，但 Codex 执行任务时以本文件、`docs/constitution.md`、当前 plan/spec/design 和 `.agents/skills/` 为准。

## 必读顺序

1. 先读 `docs/constitution.md`，任何实现、计划、评审都不得违反。
2. 再读本任务相关的 spec/design/plan。若用户没有指定，优先查看 `docs/superpowers/plans/` 下最新且与任务名称匹配的目录或 markdown。
3. 如涉及既有系统行为，读对应 ADR：`docs/adr/` 是架构决策来源。
4. 如涉及历史 Claude 执行记录，可读 `CLAUDE.md` 和旧计划中的 Claude 标注，但不要把 Claude 专用命令当作 Codex 当前事实。

## Codex 工作纪律

- 继续使用 superpowers / Spec Kit skills：本仓库的 Codex skills 放在 `.agents/skills/`，旧 `.claude/skills/` 只是迁移来源。
- 不切换 `.specify` 集成配置；它仍可能记录 `claude`，这不影响 Codex 读取 `AGENTS.md` 与 `.agents/skills/`。
- 多步改动先计划，功能或 bugfix 先测试，完成前必须给出实际验证命令和结果。
- 不覆盖用户已有改动；看到未跟踪或已修改文件，先判断是否相关，只改本任务需要的文件。
- API-first：新增/修改服务接口先改契约，再实现，再生成 client/model。
- 授权与企业隔离只能走 `PolicyEngine.can(ctx, action, resource)`；不要在 handler 中散落企业 ID 比较。
- 涉及前端体验时，保持现有产品型工具界面风格，避免营销页式布局。

## 常用验证入口

- `make sync`：同步 Python 3.12/uv 环境。
- `make gen`：OpenAPI 契约生成代码。
- `make lint`：分层检查与宪法 grep 护栏。
- `make test` 或 `uv run pytest -q`：单元测试。
- `make dev-up && make test-integration`：需要 Keycloak/MinIO 的集成测试。
- 前端相关改动优先查看 `frontend/package.json` 后使用项目已有脚本。

## 当前实现脉络

- 后端：Python 3.12 + FastAPI 微服务，`services/` 依赖 `libs/`，反向依赖禁止。
- 前端：TypeScript + Next.js/Vite 形态代码在 `frontend/`。
- 契约：`contracts/openapi/` 是接口真相源，`libs/contracts_gen/` 为生成物。
- 本地依赖：`deploy/dev/` 提供 Keycloak 26.6.2 与 MinIO。
- Omnigent 集成和 agent library 相关工作主要见 `docs/superpowers/plans/2026-06-28-omnigent-integration*`、`docs/superpowers/plans/2026-06-30-agent-library/`、`docs/adr/ADR-026*`、`docs/adr/ADR-027*`。

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
