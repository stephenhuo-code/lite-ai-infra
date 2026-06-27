from __future__ import annotations
import json
from pathlib import Path
from cryptography.fernet import Fernet

_PROVIDERS = ("claude", "codex")


class CredentialVault:
    """per-user 订阅凭据加密存储。明文绝不落盘(§5.2);仅 launch host 时解密注入。"""

    def __init__(self, key: str, store_dir: Path):
        self._f = Fernet(key.encode() if isinstance(key, str) else key)
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: str) -> Path:
        return self._dir / f"{user_id}.json"

    def _read(self, user_id: str) -> dict:
        p = self._path(user_id)
        return json.loads(p.read_text()) if p.exists() else {}

    def put(self, *, user_id: str, provider: str, secret: str) -> None:
        assert provider in _PROVIDERS, f"unknown provider: {provider}"
        data = self._read(user_id)
        data[provider] = self._f.encrypt(secret.encode()).decode()
        self._path(user_id).write_text(json.dumps(data))

    def get(self, *, user_id: str, provider: str) -> str | None:
        token = self._read(user_id).get(provider)
        return self._f.decrypt(token.encode()).decode() if token else None

    def status(self, *, user_id: str) -> dict:
        data = self._read(user_id)
        return {p: (p in data) for p in _PROVIDERS}

    def delete(self, *, user_id: str, provider: str) -> None:
        data = self._read(user_id)
        data.pop(provider, None)
        self._path(user_id).write_text(json.dumps(data))
