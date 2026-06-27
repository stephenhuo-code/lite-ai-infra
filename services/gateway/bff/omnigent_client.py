# services/gateway/bff/omnigent_client.py
# omnigent admin REST 薄客户端(header-auth)。仅 BFF 内网调 omnigent;身份经 X-Forwarded-Email
# 注入(omnigent 信任之,故 omnigent 必须不可被客户端直达 + BFF 必须剥离伪造头)。
# 建会话 = bundled(ap-web createBundledSession 契约):agent spec 打成 tar.gz(config.yaml)随
# 建会话上传,server 当场建会话级 agent 并绑定,**不需预注册 agent**。register_mcp 用 http + 令牌 url。
from __future__ import annotations

import io
import json
import tarfile

import httpx


def _agent_bundle(config_yaml: str) -> bytes:
    """把 agent config.yaml 打成 tar.gz bundle(omnigent 会话级 agent 上传格式)。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = config_yaml.encode()
        info = tarfile.TarInfo("config.yaml")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def user_message_event(text: str) -> dict:
    # SessionEventInput(探针 RESULTS 9b①):发 user turn 的事件封装。
    return {"type": "message",
            "data": {"role": "user", "content": [{"type": "input_text", "text": text}]}}


def items_to_chat(raw: list[dict]) -> list[dict]:
    # claude-native 的回复只落 items(SSE 不发 response.output_text.delta —— 那是 API-harness 才有的),
    # 故对话历史以 GET /v1/sessions/{id}/items 为准。归一化成前端 ChatItem;
    # 去重连续相同(kind,text):claude-native 把 user 消息记两次(API turn_* + forwarder 回灌 resp_claude_*)。
    out: list[dict] = []
    for it in raw or []:
        if it.get("type") == "message":
            role = it.get("role")
            if role not in ("user", "assistant"):
                continue
            text = "".join(
                b.get("text", "")
                for b in (it.get("content") or [])
                if b.get("type") in ("input_text", "output_text", "text")
            ).strip()
            if not text:
                continue
            kind = "user" if role == "user" else "assistant"
            if out and out[-1].get("kind") == kind and out[-1].get("text") == text:
                continue
            out.append({"kind": kind, "text": text})
        elif it.get("type") == "function_call":
            out.append({"kind": "tool", "name": it.get("name") or "?"})
    return out


class OmnigentClient:
    # send_identity=False:dev 单用户 omnigent(不发 X-Forwarded-Email,一切归 "local",与本地 host
    # owner 对齐;否则 alice 头会让 omnigent 按 owner 过滤掉 local 的 host → 起不了 runner)。
    # prod=header 模式必须 True。注:数据控制链路的身份(can())走 MCP 令牌,与此无关。
    # trust_env=False:连 localhost omnigent 不走代理(SOCKS 代理会断连)。
    def __init__(self, base_url: str, email: str, header: str = "X-Forwarded-Email",
                 send_identity: bool = True, transport: httpx.BaseTransport | None = None):
        headers = {header: email} if send_identity else {}
        self._c = httpx.Client(base_url=base_url.rstrip("/"), headers=headers,
                               timeout=30, trust_env=False, transport=transport)

    def post_event(self, session_id: str, event: dict) -> dict:
        # 发 turn / interrupt / approval(探针 RESULTS 9b①):POST /v1/sessions/{id}/events。
        r = self._c.post(f"/v1/sessions/{session_id}/events", json=event)
        r.raise_for_status()
        return r.json()

    def resolve_elicitation(self, session_id: str, elicitation_id: str, approve: bool) -> dict:
        # ASK 审批(探针 RESULTS 9b③):POST /elicitations/{eid}/resolve,ElicitResult。
        body = {"action": "accept" if approve else "decline"}
        r = self._c.post(f"/v1/sessions/{session_id}/elicitations/{elicitation_id}/resolve", json=body)
        r.raise_for_status()
        return r.json()

    def create_session(self, *, agent_config_yaml: str, metadata: dict | None = None) -> str:
        # bundled multipart:metadata(JSON 串)+ bundle(tar.gz)。server 返 {session_id}。
        r = self._c.post("/v1/sessions",
                         data={"metadata": json.dumps(metadata or {})},
                         files={"bundle": ("agent.tar.gz", _agent_bundle(agent_config_yaml),
                                           "application/gzip")})
        r.raise_for_status()
        return r.json()["session_id"]

    def register_mcp(self, *, session_id: str, name: str, url: str) -> None:
        r = self._c.post(f"/v1/sessions/{session_id}/agent/mcp-servers",
                         json={"name": name, "transport": "http", "url": url})
        r.raise_for_status()

    def first_online_host(self) -> str | None:
        # 取一个在线 host(runner 在其上起)。dev 单机一个 host。
        r = self._c.get("/v1/hosts")
        r.raise_for_status()
        for hst in r.json().get("hosts", []):
            if hst.get("status") == "online":
                return hst["host_id"]
        return None

    def launch_runner(self, *, host_id: str, session_id: str, workspace: str) -> str:
        # 在 host 上起 runner 并绑到会话(body 带 session_id)。无 runner 则发 turn 会 503。
        # workspace 必须是 host 上已存在的绝对路径(实证:omnigent 不自建,缺则 400)。
        r = self._c.post(f"/v1/hosts/{host_id}/runners",
                         json={"session_id": session_id, "workspace": workspace})
        r.raise_for_status()
        return r.json()["runner_id"]

    def get_items(self, session_id: str, *, limit: int = 100) -> list[dict]:
        # 会话条目(对话历史的权威来源,claude-native 回复只在此)。
        r = self._c.get(f"/v1/sessions/{session_id}/items",
                        params={"limit": limit, "order": "asc"})
        r.raise_for_status()
        return r.json().get("data", [])
