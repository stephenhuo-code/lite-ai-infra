# tests/integration/test_token_verify.py
import pytest
from libs.identity.tokens import verify_and_decode
from libs.identity.context import parse_context
pytestmark = pytest.mark.integration
JWKS = "http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs"


def test_real_token_verifies_and_parses(kc_token):
    claims = verify_and_decode(kc_token, jwks_url=JWKS)
    # 身份降两级:企业归属来自 organization claim(org alias);角色经 realm role
    ctx = parse_context(sub=claims["sub"], organization=claims.get("organization", []),
                        realm_roles=(claims.get("realm_access") or {}).get("roles", []))
    assert any(m.enterprise_id == "ent-demo" and m.role == "member" for m in ctx.memberships)
