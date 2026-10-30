import base64
import hashlib
import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import respx
from fastapi.testclient import TestClient
from veyntora_api.auth.oidc import new_pkce
from veyntora_api.health.checks import Level, ProbeResult, overall, roll_up
from veyntora_api.main import create_app
from veyntora_api.routers.auth import safe_return_to
from veyntora_api.secrets.openbao import SecretPathError, SecretWriter, last4
from veyntora_api.settings import Settings

BAO = "http://bao.test:8200"


def test_secret_writer_has_no_read_method() -> None:
    public = {
        n for n, _ in inspect.getmembers(SecretWriter, inspect.isfunction) if not n.startswith("_")
    }
    assert public == {"put", "delete", "renew_self", "close"}
    assert not any("read" in n or n == "get" for n in dir(SecretWriter))


async def test_put_writes_value_and_returns_metadata_only() -> None:
    pid = uuid4()
    expires = datetime(2027, 1, 31, tzinfo=UTC)
    with respx.mock() as mock:
        data = mock.post(f"{BAO}/v1/kv/data/providers/{pid}").respond(200, json={})
        meta = mock.post(f"{BAO}/v1/kv/metadata/providers/{pid}").respond(204)
        writer = SecretWriter(BAO, "api-token")
        ref = await writer.put(f"providers/{pid}", "sk-test-0123456789abcd9f2a", expires)
        await writer.close()
    assert data.calls.last.request.headers["X-Vault-Token"] == "api-token"
    assert b"sk-test-0123456789abcd9f2a" in data.calls.last.request.content
    assert b"sk-test" not in meta.calls.last.request.content
    assert ref.ref == f"kv/providers/{pid}"
    assert ref.last4 == "9f2a"
    assert ref.expires_at == expires
    assert "sk-test" not in repr(ref)


@pytest.mark.parametrize(
    "path",
    ["providers/../../sys/policy", "providers/not-a-uuid", "sys/mounts", f"users/{uuid4()}", ""],
)
async def test_put_rejects_paths_outside_allowed_locations(path: str) -> None:
    writer = SecretWriter(BAO, "t")
    with pytest.raises(SecretPathError):
        await writer.put(path, "value-0123456789")
    await writer.close()


def test_short_values_reveal_nothing() -> None:
    assert last4("abcd1234") is None
    assert last4("0123456789abcdef") == "cdef"


def test_pkce_challenge_is_s256_of_verifier() -> None:
    pair = new_pkce()
    digest = hashlib.sha256(pair.verifier.encode()).digest()
    assert pair.challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert 43 <= len(pair.verifier) <= 128


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/chat/123", "/chat/123"),
        ("/admin/providers?tab=keys", "/admin/providers?tab=keys"),
        (None, "/home"),
        ("https://evil.test", "/home"),
        ("//evil.test/x", "/home"),
        ("/\\evil.test", "/home"),
        ("/api/auth/logout", "/home"),
    ],
)
def test_return_to_only_allows_app_paths(value: str | None, expected: str) -> None:
    assert safe_return_to(value) == expected


def test_cookie_writes_without_csrf_header_are_refused() -> None:
    app = create_app(Settings(environment="test"))
    client = TestClient(app)  # no context manager: lifespan (external services) is not started
    client.cookies.set("vey_session", "x")
    res = client.post("/auth/logout")
    assert res.status_code == 403
    assert res.json() == {"detail": "Missing CSRF header"}


def test_status_roll_up() -> None:
    def ok(name: str, healthy: bool = True) -> ProbeResult:
        return ProbeResult(name, healthy, 1.0)

    names = [
        "postgres",
        "valkey",
        "litellm",
        "graphs",
        "qdrant",
        "openfga",
        "keycloak",
        "workers",
        "s3",
        "docling",
        "langfuse",
    ]
    healthy = {n: ok(n) for n in names}
    assert set(roll_up(healthy).values()) == {Level.OPERATIONAL}

    degraded = {**healthy, "docling": ok("docling", False)}
    levels = roll_up(degraded)
    assert levels["documents"] is Level.DEGRADED
    assert levels["chat"] is Level.OPERATIONAL
    assert overall(levels) is Level.DEGRADED

    no_idp = {**healthy, "keycloak": ok("keycloak", False)}
    assert roll_up(no_idp)["signin"] is Level.DOWN


async def test_writer_reports_store_errors() -> None:
    pid = uuid4()
    with respx.mock() as mock:
        mock.post(f"{BAO}/v1/kv/data/providers/{pid}").respond(403)
        writer = SecretWriter(BAO, "t")
        with pytest.raises(Exception, match="HTTP 403"):
            await writer.put(f"providers/{pid}", "value-0123456789")
        await writer.close()
