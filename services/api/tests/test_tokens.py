import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from veyntora_api.auth.tokens import InvalidTokenError, TokenValidator

ISSUER = "https://sso.example.test/realms/veyntora"
JWKS = "https://kc.internal/realms/veyntora/protocol/openid-connect/certs"
AUD = "veyntora-api"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    return {**data, "kid": kid, "use": "sig", "alg": "RS256"}


def _token(key: rsa.RSAPrivateKey = _KEY, kid: str = "k1", **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": [AUD, "account"],
        "sub": "user-1",
        "iat": now,
        "exp": now + 300,
        "typ": "Bearer",
        "email": "lena@example.test",
        "name": "Lena K.",
        "groups": ["/support", "/support/leads"],
    }
    claims.update(overrides)
    return jwt.encode(
        {k: v for k, v in claims.items() if v is not None}, key, "RS256", headers={"kid": kid}
    )


@pytest.fixture
async def validator() -> AsyncIterator[TokenValidator]:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(JWKS).respond(json={"keys": [_jwk(_KEY, "k1")]})
        async with httpx.AsyncClient() as http:
            yield TokenValidator(ISSUER, JWKS, AUD, http)


async def test_valid_token(validator: TokenValidator) -> None:
    claims = await validator.validate(_token())
    assert claims.sub == "user-1"
    assert claims.groups == ("/support", "/support/leads")
    assert claims.email == "lena@example.test"


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 3600},
        {"aud": "someone-else"},
        {"iss": "https://evil.example.test/realms/veyntora"},
        {"typ": "Refresh"},
        {"sub": None},
    ],
    ids=["expired", "wrong-audience", "wrong-issuer", "refresh-token", "no-subject"],
)
async def test_rejected_tokens(validator: TokenValidator, overrides: dict[str, Any]) -> None:
    with pytest.raises(InvalidTokenError):
        await validator.validate(_token(**overrides))


async def test_unknown_key_is_rejected(validator: TokenValidator) -> None:
    with pytest.raises(InvalidTokenError, match="unknown signing key"):
        await validator.validate(_token(key=_OTHER, kid="k2"))


async def test_key_mismatch_is_rejected(validator: TokenValidator) -> None:
    # Signed with another key but claiming the trusted kid.
    with pytest.raises(InvalidTokenError):
        await validator.validate(_token(key=_OTHER, kid="k1"))


async def test_alg_none_is_rejected(validator: TokenValidator) -> None:
    unsigned = jwt.encode({"sub": "x", "iss": ISSUER, "aud": AUD}, key=None, algorithm="none")
    with pytest.raises(InvalidTokenError):
        await validator.validate(unsigned)
