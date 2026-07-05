# 探针 M0:provider 凭据 → 沙箱 → harness 用上(模型配置 Phase 0)

**日期**:2026-07-01　**结论**:✅ **链通**。给 omnigent 注入一个 provider 凭据(env),该 harness 就能用上它真去调 API。**无需 fork**(只加 compose 透传 + `sandbox.docker.env` 名单)。

## 实测(真栈)
- compose 加 `OPENAI_API_KEY: ${OPENAI_API_KEY:-}`;`config.yaml` 的 `sandbox.docker.env` 加 `OPENAI_API_KEY`;export 一个**假** `OPENAI_API_KEY=sk-proj-...dummy`;重建 omnigent。
- 建 `codex-native-ui` 的 managed 会话 → 发消息。
- 沙箱容器 `env` 里 **`OPENAI_API_KEY=<set>`**(注入到位)。
- runner 日志:`native-codex routing: provider 'openai'`(codex 检测到 key、选了 openai provider)。
- codex forwarder:**`forcing failed status from turn.error: kind=auth`** → codex 拿假 key 调 OpenAI、**撞 auth 边界**。= 真 key 就能跑,链通。

## 钉死的事实(给 M1)
- `_resolve_sandbox_env`(`docker.py:186-218`)**每次 provision** 按 `sandbox.docker.env` 名单逐个 `os.environ.get(name)` 取值注入 → 改成**按会话企业读文件**即成"每企业凭据"。
- claude 订阅 + OpenAI key **同注不冲突**(不同 provider;冲突只在 claude 的订阅 vs ANTHROPIC_API_KEY 同注)。
- harness→env:codex-native 读 `OPENAI_API_KEY`/`CODEX_ACCESS_TOKEN`;claude-native 读 `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_API_KEY`。

## 决策
采纳。M1:把值来源从"全局 server env"改为"按会话企业读 `/config/model-credentials/<enterprise_id>.json`(回退全局)",并把企业 id 从会话 labels 串到 provision。owner 研判此结论后铺开。
