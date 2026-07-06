# Design(设计):企业默认智能体模板(Default Enterprise Agents)

> 设计层(HOW)。需求见 [`spec.md`](./spec.md)。执行计划见 [`../2026-07-04-agent-template-copies.md`](../2026-07-04-agent-template-copies.md)。
> **状态**:Draft(按 owner 2026-07-05 反馈修订:去 fork-heavy clone,改为企业创建/置备时创建 4 个默认本企业 agent)。

## 0. 一句话设计
把"默认智能体"做成 BFF 侧受控模板定义,企业创建/置备时调用一个幂等初始化器,用现有 `_build_bundle_bytes(...)` + `POST /v1/agents` 为企业创建 minimax、debby、codex、polly 四个**本企业** agent。它们之后就是普通企业 agent,管理员编辑/删除走现有 `PUT/DELETE /v1/ws/agents/{id}` 和 `can()`。

## 1. 设计取舍

### 推荐方案:企业创建/置备时创建受控默认模板
- **做法**:在 `services/gateway/bff/omnigent_proxy.py` 抽出默认模板定义和初始化函数;提供脚本/置备钩子传入 enterprise alias 与 omnigent base URL,幂等创建缺失的默认 agent。
- **优点**:不改 omnigent fork;不依赖 omnigent 内置模板返回 `instructions`;默认项只有 4 个,可控、可测试、快。
- **代价**:debby/polly 不再忠实复制上游富模板的 skills/mcp/capability;本版只保留我们定义的 prompt/harness/model。owner 已明确"只需要企业创建的时候有一个模版",可接受。

### 不采纳:fork `POST /agents/{id}/copy`
- 太重:新增 fork API、测试、镜像重编译、submodule bump、运行时 clone 语义。
- 解决的是"忠实复制全套 omnigent 内置模板"问题,而当前需求只是 4 个默认企业模板。

### 不采纳:首次进智能体库时惰性种子
- 用户体验和生命周期不准确:owner 要"企业创建的时候"默认有智能体。
- 读路径带写副作用,还需要额外 seed marker、防并发、防半失败。

## 2. 默认模板定义
新增一个纯数据结构,例如:

```python
@dataclass(frozen=True)
class DefaultAgentTemplate:
    key: str
    display_name: str
    harness: str
    model: str | None
    description: str
    instructions: str

DEFAULT_ENTERPRISE_AGENTS = (
    DefaultAgentTemplate(
        key="minimax",
        display_name="minimax",
        harness="openai-agents",
        model="MiniMax-Text-01",
        description="OpenAI 兼容 provider 模板,默认用于 MiniMax。",
        instructions="你是 minimax 智能体,使用企业配置的 OpenAI 兼容 provider 回答问题。",
    ),
    DefaultAgentTemplate(
        key="debby",
        display_name="debby",
        harness="claude-sdk",
        model=None,
        description="多视角讨论与审查助手。",
        instructions="你是 Debby,负责从多个角度审查问题、提出反例和改进建议。",
    ),
    DefaultAgentTemplate(
        key="codex",
        display_name="codex",
        harness="codex",
        model=None,
        description="代码实现和修改助手。",
        instructions="你是 Codex,负责阅读代码、提出实现计划并谨慎修改项目文件。",
    ),
    DefaultAgentTemplate(
        key="polly",
        display_name="polly",
        harness="claude-sdk",
        model=None,
        description="任务拆解与协作编排助手。",
        instructions="你是 Polly,负责把目标拆成可执行任务,协调多个实现者并汇总结果。",
    ),
)
```

说明:
- `key` 用于幂等匹配,不是用户展示字段。
- `display_name` 进入 `description` 首行,仍遵守现有 `_encode_description()` 约定。
- `harness/model/instructions/description` 通过现有 bundle 白名单写入 omnigent。
- 不写 `executor.auth`,凭据继续由模型配置注入。

## 3. 幂等创建策略
- 读取 omnigent `GET /v1/agents` 全量。
- 用现有 `_split_enterprise(name)` 判断本企业 agent。
- 对本企业已有 agent,用 `_decode_description(description)` 取展示名;若展示名等于默认模板 `display_name`,视为已存在,不覆盖、不重复创建。
- 对缺失模板,调用现有 bundle 构建逻辑创建:
  - `name = _enterprise_name(alias, template.display_name)`
  - `description = _encode_description(template.display_name, template.description)`
  - `instructions = template.instructions`
  - `harness = template.harness`
  - `model = template.model`
  - `api_key/base_url = None`
- 返回结果包含 created/skipped/failed,供企业置备脚本或未来企业创建 API 显式反馈。

该策略满足:
- 重复运行不重复。
- 管理员改过 prompt/description 后不被覆盖。
- 管理员删除某默认 agent 后,普通初始化不会自动复活;只有显式补种才会补缺失。

## 4. 触发点
本版建议拆成两个层次:

1. **核心能力**:BFF 模块暴露 `ensure_default_agents_for_enterprise(alias, *, omni_base_url, identity_email, transport=None) -> DefaultAgentSeedResult`。它不依赖用户会话,用于系统置备。
2. **dev/ops 入口**:新增 `scripts/provision_default_agents.py --enterprise ent-demo`,在 `make ws-up` 或 `scripts/provision_orgs.py` 后调用。生产企业创建服务未来调用同一核心能力。

原因:
- 当前仓库没有真正的"创建企业 API";dev 只有 `scripts/provision_orgs.py` 通过 KC Admin 创建/确保 org。
- 把默认 agent 初始化写成独立幂等能力,比塞进登录/列表读路径更清晰,也便于生产企业创建流程复用。

## 5. 列表与编辑语义
- 默认智能体创建后就是普通本企业 agent,`GET /v1/ws/agents` 返回它们,并标记 `enterprise_owned=true,builtin=false`。
- 企业侧列表明确**隐藏 omnigent 内置模板**(`owner is None`),避免出现同名默认企业 agent 与只读内置 agent 并列。
- 企业管理员现有 `PUT /v1/ws/agents/{id}` 可编辑默认智能体。
- 企业管理员现有 `DELETE /v1/ws/agents/{id}` 可删除默认智能体。
- 普通成员无编辑/删除入口,服务端 `can(agent:configure/delete)` 继续兜底。
- 隐藏内置只改 BFF 列表过滤和前端测试,不需要 fork。

## 6. 授权 · 安全 · 隔离
- 默认初始化是**系统置备动作**,不是普通用户自助创建;不走用户 `can(agent:create)`。生产接入时应只由企业创建服务/ops 脚本调用。
- 用户后续编辑/删除仍走 `can(agent:configure/delete)`。
- 归属仍编码在 omnigent agent `name` 前缀中:`<alias>_<ascii-slug>-<rand>`。
- alias 仍必须满足 `_ALIAS_RE = ^[a-zA-Z0-9-]+$`,避免 `_` 分隔错切导致跨企业泄漏。
- 默认模板不包含密钥;不写 `executor.auth`;所有 provider 凭据继续来自 `ModelConfig`。
- 创建失败必须显式返回/打印,不得把半成功伪装成企业已就绪。

## 7. 非功能
- **性能**:固定 4 个模板,顺序创建足够;无需并发。
- **幂等**:按本企业展示名匹配缺失项,补缺不覆盖。
- **dev-prod parity**:核心创建逻辑复用 BFF bundle 构造;dev 脚本和生产企业创建服务调用同一函数。
- **审计**:系统置备创建默认智能体时写 `agent:seed-default` 或复用 `agent:create` 审计,metadata 标记 `default_template=<key>`;不得写凭据。

## 8. ADR-027 增量
需要把 ADR-027 里"内置模板全局共享只读 + 本企业创建"补一段增量:
- 新企业默认拥有 4 个本企业 agent(minimax/debby/codex/polly)。
- 默认 agent 由 Lite AI 模板定义生成,不 fork clone omnigent 内置 bundle。
- 企业管理员可编辑/删除默认 agent;这不会影响平台模板或其它企业。
- 凭据仍走企业模型配置/平台默认,不进入 agent bundle。

## 9. 验收与测试策略
- **单元(BFF/脚本)**:
  - 默认模板定义正好包含 minimax/debby/codex/polly,并带预期 harness/model。
  - 对空企业初始化 → 发 4 次 `POST /v1/agents`,bundle name 均带企业前缀,description 首行为展示名。
  - 已有 debby 时初始化 → 只创建缺失 3 个,不覆盖 debby。
  - 重复初始化 → 第二次 0 created。
  - 跨企业初始化 → A/B 生成各自前缀,互不混淆。
  - 列表过滤 → 只返回本企业 agent,不返回 `owner is None` 的内置模板。
  - 普通成员编辑/删除仍 403(现有测试保留)。
- **前端/页面**:
  - 智能体库文案改成"本企业智能体,新企业默认包含 minimax/debby/codex/polly"。
  - 隐藏内置模板,测试同步移除"内置可见"断言。
- **手动 runbook**:
  - `make ws-up` 后运行默认 agent 置备。
  - 打开智能体库,确认 minimax/debby/codex/polly 为"本企业"。
  - 编辑 debby、删除 polly,刷新后状态正确。

## ★ DoR 就绪门自评(owner 复核)
| # | 就绪项 | 状态 |
|---|---|---|
| 1 | 范围与出口 | ✅ 固定 4 个默认企业 agent;去掉 fork clone/全量复制 |
| 2 | 接口契约 | ✅ 无新对外用户 API;系统置备入口/脚本调用内部能力 |
| 3 | 数据模型 | ✅ 默认 agent = 现有 omnigent agent + 企业前缀;无新持久表 |
| 4 | 外部依赖事实 | ✅ 现有 `POST /v1/agents` 已可创建安全 bundle;无需新 fork |
| 5 | 行为·边界·并发·威胁 | ✅ 幂等补缺、不覆盖、不跨企业、不写密钥 |
| 6 | NFR | ✅ 固定 4 个模板,性能简单;dev/prod 复用同一核心逻辑 |
| 7 | 验收与测试 | ✅ 单元 + runbook 验证点明确 |
| 8 | 关键决策留痕 | ✅ 需更新 ADR-027 增量,记录"默认企业模板定义,不 fork clone" |
