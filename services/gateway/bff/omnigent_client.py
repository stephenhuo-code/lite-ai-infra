# services/gateway/bff/omnigent_client.py
# omnigent admin REST 薄客户端(header-auth)。仅 BFF 内网调 omnigent;身份经 X-Forwarded-Email
# 注入(omnigent 信任之,故 omnigent 必须不可被客户端直达 + BFF 必须剥离伪造头)。
# Task0 实证:create_session 需 agent_id;register_mcp 用 http transport + 令牌化 url。
from __future__ import annotations

import httpx


def user_message_event(text: str) -> dict:
    # SessionEventInput(探针 RESULTS 9b①):发 user turn 的事件封装。
    return {"type": "message",
            "data": {"role": "user", "content": [{"type": "input_text", "text": text}]}}


class OmnigentClient:
    def __init__(self, base_url: str, email: str, header: str = "X-Forwarded-Email",
                 transport: httpx.BaseTransport | None = None):
        self._c = httpx.Client(base_url=base_url.rstrip("/"),
                               headers={header: email}, timeout=30, transport=transport)

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

    def create_session(self, agent_id: str) -> str:
        r = self._c.post("/v1/sessions", json={"agent_id": agent_id})
        r.raise_for_status()
        return r.json()["id"]

    def register_mcp(self, *, session_id: str, name: str, url: str) -> None:
        r = self._c.post(f"/v1/sessions/{session_id}/agent/mcp-servers",
                         json={"name": name, "transport": "http", "url": url})
        r.raise_for_status()
