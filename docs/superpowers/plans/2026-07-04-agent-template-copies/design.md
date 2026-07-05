# Design(设计):企业模板副本(Agent Template Copies)

> 设计层(HOW)。需求见 [`spec.md`](./spec.md)。**引用既有家、不复制**:契约/实现现状 → `services/gateway/bff/omnigent_proxy.py`;归属编码/授权 → [ADR-027](../../../adr/ADR-027-agent-library.md);per-enterprise 文件约定 → `services/gateway/bff/model_config.py`;授权唯一出入口 → `libs/authz/engine.py`。
> **状态**:Draft(待 owner DoR 过门)。

## 0. 一句话设计
在 `GET /v1/ws/agents` 的**读路径**上加一步**惰性、一次性、系统级**的"种子":某企业首次进库且无种子标记时,把**平台模板**(omnigent 无前缀全局 agent)逐个复制成**本企业**智能体(复用现有建 agent 的 bundle + 前缀编码),写下**每企业种子标记**;此后企业侧列表**只返回本企业副本**、不再并列内置。编辑/删除**沿用现有本企业路径**,零改动。

## 1. 架构与隔离
- **平台模板 = 不可见种子源**:omnigent 里无企业前缀的 agent(`builtin = owner is None`,见 `omnigent_proxy.py:_split_enterprise/_visible_to`)。企业侧**任何**操作都不写它 → 隔离天然成立。
- **副本 = 本企业资源**:沿用 ADR-027 as-built 归属编码——`name = "<alias>_<ascii-id>"`(SEP=`_`),展示名/描述落 `description`(首行展示名,空行后描述)。`enterprise_owned = (owner == alias)`。
- **隔离不变式**(不变,复用现有 guard):
  - alias 必须 `_`-free(`^[a-zA-Z0-9-]+$`),否则前缀还原错切 → 跨企业泄漏。由 `_resolve_ctx` guard 强制(现有)。
  - 列表/建会话/改删的企业过滤与归属校验**全在 BFF**,前端不可直达 omnigent(现有信任边界)。
- **新增:企业侧列表不再显示内置**。种子后企业看到的都是本企业副本;平台模板对企业用户不可见(仅作种子源)。

## 2. 种子流程(惰性 · 一次性 · 系统级)
入口:`GET /v1/ws/agents`(现 `omnigent_proxy.py` 的 `agents()` handler)。伪流程:

```
resolve alias（已认证会话，现有 _resolve_ctx）
if not seed_marker_exists(alias):
    if try_claim_seed(alias):            # 原子占坑，防并发双种
        try:
            templates = fetch_platform_templates()      # omnigent 无前缀 agent
            for t in templates:
                copy_as_enterprise_agent(alias, t)       # 复用建 agent 的 bundle+前缀
            finalize_seed_marker(alias, templates)       # 落最终标记（记 seeded_at + 源模板）
        except:
            release_seed_claim(alias)     # 失败释放占坑 → 下次重试；不留“已完成”假标记
            raise / fall through
    else:
        wait/skip                         # 输给别的请求，跳过（列表照常返回，可能少几条，下次刷新齐）
list = fetch enterprise-owned agents for alias   # 只本企业副本
return list（剥前缀、拆展示名，现有逻辑）
```

- **copy_as_enterprise_agent = 走 fork 新增的服务端 clone**(见 §2.1)。**探得事实(2026-07-04)**:omnigent 的 `AgentObject`(`third_party/omnigent/omnigent/server/routes/builtin_agents.py:_to_agent_object`)**不返回 `instructions`/`model`**——只有 id/name/version/description/harness/mcp_servers/skills/terminals。故 BFF **无法**从 list 拿到系统提示词来忠实重搭;且 `_build_bundle_bytes` 只写安全字段(丢 skills/mcp/能力位),对 debby/polly 这类富模板会残废。→ **改为服务端 clone**:在 fork 里复制模板存储的整份 bundle、只把 name 换成企业前缀名再注册,**instructions/model/skills/mcp/能力位全保留**。

### 2.1 fork 服务端 clone 端点(owner 拍板方案 A)
- **新增**:`POST /v1/agents/{id}/copy`(fork,`builtin_agents.py`),form/query 传目标 `name`(企业前缀名,BFF 据已认证 alias 生成)。
- **逻辑**(复用现成件,纯加法):`agent_store.get(id)` 取源模板(须 `session_id IS NULL`,否则 404)→ `artifact_store.get(agent.bundle_location)` 读 bundle bytes → 解出 `config.yaml`、**改 `name`=目标名(必填)+ `description`=目标描述(BFF 传,选填)**、其余(instructions/executor/llm/skills/mcp/能力位)**原样保留** → 重新打 tar → 交给启动期同一个 `_ensure_builtin_agent(agent_store, artifact_store, agent_cache, name=目标名, bundle_bytes=新 bytes)` 注册(idempotent by name,`session_id IS NULL`,与现有建 agent 同类)→ `agent_store.get_by_name(目标名)` → `_to_agent_object` 返回。
- **description 也要改的原因**:clone 原样复制会带上模板的自由文本 description;而 BFF 对「本企业 agent」的约定是 description 首行=展示名(`_encode_description/_decode_description`)。故 BFF 调 copy 时传 `description=_encode_description(模板名, 模板原描述)`,让副本符合展示名约定;instructions/skills/mcp **不受影响,保持忠实**。
- **不套用户上传白名单**:clone 走**启动期 seeding 路径**(直接 `_ensure_builtin_agent`),**不调** `_assert_safe_builtin_spec`(那是防 UNTRUSTED 上传的字段白名单)——源是已注册的受信模板,保留其 skills/mcp/能力位正当。仅结构校验 + name 正则(`^[a-zA-Z0-9_-]+$`)。
- **信任**:源是**受信的 operator 模板**(session_id NULL),clone 保留其全部字段(含 skills/mcp/spawn 等能力位)是正当的——**不套用户上传的安全白名单**(那是防 UNTRUSTED 上传;clone 内容源自平台模板,非客户端输入)。目标 `name` 由 BFF 生成、仍受 omnigent name 校验(`^[a-zA-Z0-9_-]+$`)。
- **鉴权**:同现有 agent 路由的 header-trust;"谁能触发/给哪个企业"仍由 **BFF** 把关(BFF 供前缀名 = 会话 alias,客户端不可指定)。
- **可 upstream**:与 ADR-027 §1「小 fork 暴露 omnigent 自身逻辑」一脉;提交进 fork(模型 C)→ `omnigent_build.sh dev` 重编译 → bump submodule。
- **BFF 侧 copy_as_enterprise_agent**:对每个模板 `POST {omni}/v1/agents/{template_id}/copy` with `name=_enterprise_name(alias, template_display)`;**不带 per-agent 凭据**(clone 保留模板原样,模板本就无 per-agent key → 继续用全局订阅/模型配置注入,红线不破)。
- **系统级、不过 `agent:create` 门**:种子不是"用户建 agent",是平台为企业做初始化。**不调 `can(agent:create)`**(那门要 enterprise-admin);仅凭已认证会话解析出的 alias 执行。内容是平台模板(受信)、非用户输入,落点只在本企业 → 不放大越权面。**用户对副本的编辑/删除仍走原 `can(agent:configure/delete)` 的 enterprise-admin 门(不变)。**

## 3. 种子标记(每企业一次性)
- **载体**:每企业一份标记文件,复用 model-config 的 per-enterprise 文件约定(`model_config.py` 用 `secrets/model-config/<alias>.json`,env `MODEL_CONFIG_DIR` 覆盖)。本功能用**独立目录**:`secrets/agent-seed/<alias>.json`,env `AGENT_SEED_DIR` 覆盖(测试指临时目录,绝不碰真 secrets/)。
- **状态三态(用文件名/字段表达)**:
  - 无文件 = 未种子。
  - `<alias>.seeding`(claim 锁)= 正在种(占坑,防并发)。
  - `<alias>.json`(最终标记)= 已种子;内容记 `{ seeded_at, source_template_ids: [...], count }`(seeded_at 由调用方传入时间戳注入,避免脚本内取时钟)。
- **原子占坑 try_claim_seed**:以 `O_CREAT|O_EXCL` 建 `.seeding` 文件——成功=拿到种子权;`FileExistsError`=别人在种,跳过。种成功后:写 `.json` 最终标记 → 删 `.seeding`。种失败:删 `.seeding`(释放,下次重试)。
- **为何不用"库里有无本企业 agent"作判据**:那会导致 US3 复活(全删后又被种满)。持久标记是"只种一次"的唯一可靠依据。

## 4. 列表语义变化(企业侧只见副本)
- 现 `agents()` 返回"本企业可见 = 内置 + 本企业"。**改为:企业上下文只返回本企业 `enterprise_owned` 副本**;内置(无前缀)**不并入企业列表**。
- `builtin` 字段对企业列表恒为 false(企业侧无内置);保留字段以兼容前端类型。
- **前端**(`frontend/src/pages/Agents.tsx`):副本都是 `enterprise_owned=true && !builtin` → 现有 `ownEditable` 条件天然对管理员显示"编辑/删除"。**无需为内置单独开编辑口**;`内置` 徽标分支实际不再命中(可保留死代码或清理,tasks 定)。**无新端点**——GET 复用、PUT/DELETE 复用。

## 5. 数据流与状态
- **无新持久实体**:副本是普通 omnigent agent(存 omnigent postgres,现有);标记是文件(BFF 侧 volume)。
- **种子源 → 副本映射**:一对一,按模板顺序复制;副本的 ascii-id 用稳定生成(现有 `_ascii_slug`/id 生成逻辑,tasks 复核)。
- **历史遗留企业(上线前已建过本企业 agent)**:**已定(owner)**——**首次触发种子时若检测到本企业已有 `enterprise_owned` agent,则只补落最终标记、跳过复制**(视为"已初始化",避免与既有重复)。dev 的 ent-demo(已有测试建的本企业 agent)据此不会被再种一套。

## 6. 授权 · 安全 · 红线
- **授权唯一出入口不破**:用户对副本的读(列表隔离)/改/删仍经 `can()`(现有 `agent:configure/delete` = enterprise-admin;跨企业硬隔离)。**种子是系统初始化,显式不经 `can(agent:create)`**——在 design/ADR 留痕说明"为何这一步不过用户授权门"。
- **副本无 per-agent 凭据**:`executor.auth` 留空,继承全局共享订阅(与 ADR-027 §4 现状一致);`_contains_env_ref` 等现有 bundle 安全校验仍适用(种子内容来自模板,天然无 `${}` 注入面)。
- **信任边界不变**:种子只在 BFF 内、凭已认证 alias 触发;前端/客户端无法指定"给哪个企业种"(alias 来自会话,不来自请求体)。
- **隔离不变式**:copy 落点 name 前缀 = 会话 alias;alias `_`-free guard 复用。跨企业不可能被种进别家。

## 7. 非功能(NFR)
- **性能/规模**:模板约十余个;种子 = 十余次顺序 `POST /v1/agents`。目标首次进库端到端 ≤ 3s(SC-005)。若超,tasks 可评估并发复制(有界)——非首版必需。
- **并发**:同企业并发首次进库 → `O_EXCL` 占坑保证只种一次;输的请求本次列表可能少几条,刷新即齐(可接受;或输方短等占坑释放后再列,tasks 定)。
- **失败/幂等**:种子中途失败释放占坑、不落最终标记 → 下次重试。重试可能撞已建的部分副本——因 name/id 稳定,omnigent 按 name upsert(现有 `POST /v1/agents` 幂等语义),不产生重复。
- **dev-prod parity**:种子逻辑纯在 BFF,dev/prod 同源;标记文件路径靠 env,prod 指向持久卷。
- **审计**(§6.1):种子复制的每个副本可选审计一条 `agent:seed`(actor=触发用户 or system、企业、源模板、结果);至少对首版记"种子完成"一条。tasks 定粒度。

## 8. ADR-027 增量(本设计带来的模型变更)
> **已定(owner)**:**修订 ADR-027**——在其中加一节增量记录本次模型转变(作为一个实现任务落地,与代码同 PR)。下列为该增量要点。

- **模型转变**:从"内置模板全局共享**只读** + 本企业创建(§2/§4')"→ "**每企业首次进库惰性获得全套模板的可编辑副本**;平台模板降级为**企业侧不可见的种子源**"。
- **§4'"内置模板不可编辑"作废**:企业侧不再有"内置"这一可操作对象;所有企业可见 agent 皆本企业副本、可编辑可删。
- **新增授权留痕**:种子这一步**系统级、不过 `can(agent:create)`**;其正当性 = 内容受信(平台模板)、落点受隔离约束(会话 alias)、不放大越权面。
- **新增小 fork**:`POST /v1/agents/{id}/copy`(服务端 clone,§2.1)——延续 §1「小 fork 复用内部 seeding、可 upstream」;faithful copy 的唯一途径(list 不暴露 instructions)。
- **不变**:归属编码(SEP=`_`+前缀)、per-agent 无凭据(全局订阅)、编辑/删除的 enterprise-admin 门、信任边界。

## 9. 验收与测试策略
- **手动 runbook**:更新 [`../2026-06-28-omnigent-integration/RUNBOOK.md`](../2026-06-28-omnigent-integration/RUNBOOK.md) 的智能体库段(原智-1/智-2/智-5):新企业首次进库自动出全套可编辑副本;改/删"源自模板"副本成功;删光不复活;跨企业互不影响。
- **单元(BFF,无需起栈)**,扩 `tests/gateway/bff/test_agents.py`:
  - 首次进库(无标记)→ 种 N 份 `enterprise_owned` 副本、落最终标记、列表返回副本(不含内置)。
  - 二次进库(有标记)→ 不重复种。
  - 删若干/全删后重进 → 不复活(SC-003)。
  - 并发两请求 → 只种一次(占坑)。
  - 成员触发首次进库 → 种子发生、成员可见但改/删仍 403(US5)。
  - 跨企业:B 首次进库种 B 的、看不到 A 的;A 改/删不影响 B 与平台模板(SC-004)。
  - 历史遗留企业(已有本企业 agent)首次触发 → 按策略跳过复制、补标记。
  - **改写/替换**原"内置全局可见"用例(语义已变)。
- **DoD**:上述单元全绿 + runbook 手动过 + `make lint` 宪法 grep 护栏绿。

## ★ DoR 就绪门自评(owner 复核)
| # | 就绪项 | 状态 |
|---|---|---|
| 1 | 范围与出口 | ✅ spec 范围/推迟清晰;出口=智能体库读路径 + 现有改删 |
| 2 | 接口契约 | ✅ 复用现有 `GET/PUT/DELETE /v1/ws/agents`,**无新对外端点**;种子为内部读路径副作用 |
| 3 | 数据模型 | ✅ 副本=现有 agent+前缀;标记文件三态 schema 与路径已定 |
| 4 | 外部依赖事实 | ✅ 建/列/删已实测;**新探得(2026-07-04)**:AgentObject 不返回 instructions/model → faithful copy 需服务端 clone(§2.1,owner 拍板方案 A) |
| 5 | 行为·边界·并发·威胁 | ✅ 复活/并发/半失败/历史遗留/成员触发 均有策略(§3/§5/§7) |
| 6 | 非功能(NFR) | ✅ 隔离不变式/parity/secret(无 per-agent 凭据)/性能目标 已述 |
| 7 | 验收与测试 | ✅ runbook 更新点 + 单元清单 + DoD |
| 8 | 关键决策留痕 | ✅ **已定(owner)**:修订 ADR-027(§8 增量,作为实现任务与代码同 PR);历史遗留企业=跳过复制补标记(§5) |
