# 架构宪法（必读·不可违反）

**开始任何编码 / 计划 / 评审前，ALWAYS 先读并遵守 [`docs/constitution.md`](docs/constitution.md)。** 它是本项目的硬纪律（多企业租户与标识、身份与授权、微服务 + API 优先、审计与数据、版本路线、CI 防线），来源为 ADR-002/010/011/012/024/025 + design spec。**多企业租户与标识（ADR-025）：企业 = KC Organization 的不透明 alias，身份降两级（平台→企业→用户，v1 移除用户组层），企业归属随 token 的 `organization` claim；自助注册按邮箱域自动归企业 + 邀请；用户组 / per-group 授权 = vN+（Cerbos）。** 与具体实现冲突时以宪法为准；宪法变更必须走 ADR。

详细设计见 `docs/superpowers/specs/2026-05-08-llm-infra-platform-design.md` 与 `docs/adr/`。

---

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
