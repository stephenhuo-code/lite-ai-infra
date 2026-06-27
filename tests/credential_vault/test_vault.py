from services.credential_vault.vault import CredentialVault


def test_put_get_roundtrip_encrypts_at_rest(tmp_path):
    v = CredentialVault(key="izUz8HYmu8l-FHzVXypDBEyGRuf33opI-Jf3xGaLgaw=", store_dir=tmp_path)
    v.put(user_id="u-alice", provider="claude", secret="oauth-tok-123")
    blob = (tmp_path / "u-alice.json").read_bytes()
    assert b"oauth-tok-123" not in blob          # 落盘必须密文
    assert v.get(user_id="u-alice", provider="claude") == "oauth-tok-123"


def test_status_and_delete(tmp_path):
    v = CredentialVault(key="izUz8HYmu8l-FHzVXypDBEyGRuf33opI-Jf3xGaLgaw=", store_dir=tmp_path)
    v.put(user_id="u-bob", provider="codex", secret='{"OPENAI_API_KEY":"x"}')
    assert v.status(user_id="u-bob") == {"claude": False, "codex": True}
    v.delete(user_id="u-bob", provider="codex")
    assert v.status(user_id="u-bob") == {"claude": False, "codex": False}


def test_get_missing_returns_none(tmp_path):
    v = CredentialVault(key="izUz8HYmu8l-FHzVXypDBEyGRuf33opI-Jf3xGaLgaw=", store_dir=tmp_path)
    assert v.get(user_id="nobody", provider="claude") is None
