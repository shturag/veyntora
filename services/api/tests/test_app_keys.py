"""API app keys and the API-to-graph-server tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.auth import internal
from veyntora_api.channels import app_keys
from veyntora_api.db.models.identity import User
from veyntora_api.routers.admin_channels import CreatedKey, _out

from tests.test_providers import CTX

SECRET = "test-internal-secret-0123456789abcdefghij"


async def _admin(db: AsyncSession) -> User:
    user = User(keycloak_sub="sub-keys", email="keys@example.com", display_name="Keys")
    db.add(user)
    await db.flush()
    return user


async def test_a_key_has_its_own_identity_is_shown_once_and_stored_hashed(db: AsyncSession) -> None:
    admin = await _admin(db)
    row, key = await app_keys.create(db, CTX, app_keys.AppKeyInput(name="CRM"), admin.id)
    assert key.startswith(f"vey_ak_{row.key_prefix}_") and key not in row.key_hash
    identity = await db.get(User, row.service_user_id)
    assert identity is not None and identity.is_service and identity.display_name == "App: CRM"
    assert identity.keycloak_sub.startswith("service:"), "never a Keycloak account"
    listed = (await _out(db, row)).model_dump_json()
    assert key not in listed and row.key_hash not in listed
    assert CreatedKey(**(await _out(db, row)).model_dump(), key=key).key == key

    found = await app_keys.authenticate(db, key)
    assert found is not None and found[1].id == identity.id and row.last_used_at is not None
    assert await app_keys.authenticate(db, key[:-1] + ("A" if key[-1] != "A" else "B")) is None
    assert await app_keys.authenticate(db, "vey_ak_short") is None


async def test_revoked_expired_or_suspended_keys_stop_at_once(db: AsyncSession) -> None:
    admin = await _admin(db)
    row, key = await app_keys.create(db, CTX, app_keys.AppKeyInput(name="Expiring"), admin.id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await app_keys.authenticate(db, key) is None

    row2, key2 = await app_keys.create(db, CTX, app_keys.AppKeyInput(name="Bot"), admin.id)
    identity = await db.get(User, row2.service_user_id)
    assert identity is not None
    identity.suspended = True
    assert await app_keys.authenticate(db, key2) is None
    identity.suspended = False
    await app_keys.revoke(db, CTX, row2)
    assert await app_keys.authenticate(db, key2) is None and identity.suspended
    with pytest.raises(app_keys.AppKeyError, match="future"):
        await app_keys.create(
            db, CTX, app_keys.AppKeyInput(name="x", expires_at=datetime.now(UTC)), admin.id
        )


def test_internal_tokens_are_short_lived_and_only_for_the_graph_server() -> None:
    token = internal.mint(SECRET, "service:abc", "app_key")
    claims = internal.verify(SECRET, token)
    assert claims["sub"] == "service:abc" and claims["aud"] == "veyntora-graphs"
    assert int(claims["exp"]) - int(claims["iat"]) == internal.TTL_SECONDS  # type: ignore[call-overload]
    with pytest.raises(internal.InternalTokenError):
        internal.verify(SECRET + "x", token)
    other = jwt.encode({**claims, "aud": "veyntora-api"}, SECRET, algorithm="HS256")
    with pytest.raises(internal.InternalTokenError):
        internal.verify(SECRET, other)
    with pytest.raises(internal.InternalTokenError, match="32"):
        internal.mint("short", "x", "widget")


def test_the_graph_server_accepts_api_tokens_only_with_the_shared_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veyntora_graphs import auth  # noqa: PLC0415

    monkeypatch.setattr(auth, "_INTERNAL_SECRET", SECRET)
    claims = auth.verify(internal.mint(SECRET, "service:abc", "app_key"))
    assert claims["sub"] == "service:abc"
    forged = internal.mint("another-secret-0123456789abcdefghijkl", "sub-admin", "widget")
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify(forged)


def test_widget_websites_must_be_plain_https_origins() -> None:
    from veyntora_api.channels.widget import WidgetConfig  # noqa: PLC0415

    cfg = WidgetConfig(
        enabled=True,
        allowed_origins=[
            "https://intranet.example.com/",
            "http://localhost:3001",
            "https://intranet.example.com",
        ],
    )
    assert cfg.allowed_origins == ["http://localhost:3001", "https://intranet.example.com"]
    for bad in [
        "http://intranet.example.com",
        "https://x.example.com/page",
        "javascript:alert(1)",
        "*",
    ]:
        with pytest.raises(ValueError):
            WidgetConfig(allowed_origins=[bad])


def test_widget_tokens_are_for_one_chatbot_and_not_internal_tokens() -> None:
    token = internal.mint_widget(SECRET, "sub-anna", "bot-1")
    claims = internal.verify_widget(SECRET, token)
    assert (claims["sub"], claims["bot"]) == ("sub-anna", "bot-1")
    assert int(claims["exp"]) - int(claims["iat"]) == internal.WIDGET_TTL_SECONDS  # type: ignore[call-overload]
    with pytest.raises(internal.InternalTokenError):
        # A graph-server token cannot be used as a widget token, and the other way round.
        internal.verify_widget(
            SECRET, internal.WIDGET_PREFIX + internal.mint(SECRET, "sub-anna", "widget")
        )
    with pytest.raises(internal.InternalTokenError):
        internal.verify(SECRET, token[len(internal.WIDGET_PREFIX) :])
