# services/gateway/bff/omnigent_fs.py
# omnigent environment filesystem 适配(9d 真实 syncer)。契约取自 ap-web(探针 RESULTS 9d):
#   读 GET …/environments/{eid}/filesystem/{path} → {content, encoding(utf-8|base64)}
#   写 PUT …/filesystem/{path} body {content, encoding}
#   列变更 GET …/changes → {changes:[{path}]}(只回写本会话改过的文件)
# 形状为 hydrate/persist 期望的 fs(read/write/listrel),可直接替换注入式假件。header-auth 身份。
from __future__ import annotations

import base64

import httpx


class OmnigentFs:
    def __init__(self, *, base_url: str, session_id: str, environment_id: str, email: str,
                 header: str = "X-Forwarded-Email", transport: httpx.BaseTransport | None = None):
        self._c = httpx.Client(base_url=base_url.rstrip("/"), headers={header: email},
                               timeout=30, transport=transport)
        self._base = f"/v1/sessions/{session_id}/resources/environments/{environment_id}"

    def read(self, rel: str) -> bytes:
        r = self._c.get(f"{self._base}/filesystem/{rel}")
        r.raise_for_status()
        j = r.json()
        if j.get("encoding") == "base64":
            return base64.b64decode(j["content"])
        return j["content"].encode()

    def write(self, rel: str, data: bytes) -> None:
        r = self._c.put(f"{self._base}/filesystem/{rel}",
                        json={"content": base64.b64encode(data).decode(), "encoding": "base64"})
        r.raise_for_status()

    def listrel(self) -> list[str]:
        r = self._c.get(f"{self._base}/changes")
        r.raise_for_status()
        return [c["path"] for c in r.json().get("changes", [])]
