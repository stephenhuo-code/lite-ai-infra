# tests/integration/test_token_verify.py
import pytest
from libs.identity.tokens import verify_and_decode
from libs.identity.context import parse_context
pytestmark = pytest.mark.integration
JWKS = "http://localhost:8080/realms/lite-ai/protocol/openid-connect/certs"


def test_real_token_verifies_and_parses(kc_token):
    claims = verify_and_decode(kc_token, jwks_url=JWKS)
    ctx = parse_context(sub=claims["sub"], groups=claims.get("groups", []))
    assert any(m.enterprise_id == "e-0001" and m.role == "member" for m in ctx.memberships)
