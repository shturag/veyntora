"""Own models (BYOK): stored write-only, tested before storing, public endpoints only."""

from __future__ import annotations

import pytest
import respx
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.governance import AuditEvent
from veyntora_api.db.models.identity import User
from veyntora_api.providers import byok
from veyntora_api.providers.service import ProviderError, purge_replaced_keys
from veyntora_api.routers.me_settings import ByokOut

from tests.test_providers import CTX, FakeWriter

KEY = "sk-own-0123456789abcdefLAST"
ENDPOINT = "https://1.1.1.1/v1"


class DeletingWriter(FakeWriter):
    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[str] = []

    async def delete(self, path: str) -> None:
        self.deleted.append(path)


async def _user(db: AsyncSession) -> User:
    user = User(keycloak_sub="sub-byok", email="own@example.com", display_name="Own")
    db.add(user)
    await db.flush()
    return user


def _input(**kw: object) -> byok.ByokInput:
    base: dict[str, object] = {
        "label": "My GPT",
        "adapter": "openai_compatible",
        "endpoint": ENDPOINT + "/",
        "model": "gpt-x",
        "key": SecretStr(KEY),
    }
    return byok.ByokInput.model_validate({**base, **kw})


@respx.mock
async def test_own_key_is_tested_then_stored_write_only(db: AsyncSession) -> None:
    models = respx.get(f"{ENDPOINT}/models").respond(200, json={"data": []})
    user, writer = await _user(db), DeletingWriter()
    row = await byok.add_key(db, CTX, writer, user.id, _input())  # type: ignore[arg-type]
    assert models.calls.last.request.headers["authorization"] == f"Bearer {KEY}"
    assert writer.stored == {f"users/{user.id}/{row.id}": KEY}
    assert row.endpoint == ENDPOINT and row.secret_last4 == "LAST" and row.use_for == "chats"
    out = ByokOut.of(row).model_dump_json()
    assert KEY not in out and "kv/users" not in out
    events = await db.execute(sa.select(AuditEvent).where(AuditEvent.target_id == str(row.id)))
    for e in events.scalars():
        assert KEY not in str(e.before) and KEY not in str(e.after)

    # A second model for chats replaces the first one in that role.
    second = await byok.add_key(db, CTX, writer, user.id, _input(label="Other"))  # type: ignore[arg-type]
    await db.refresh(row)
    assert (row.use_for, second.use_for) == ("none", "chats")

    # Replacing the key keeps the old one for the grace period; removing deletes all versions.
    await byok.replace_secret(
        db,
        CTX,
        writer,
        second,
        value=SecretStr(KEY + "2"),
        expires_at=None,
        grace="24h",  # type: ignore[arg-type]
    )
    assert second.previous_secret_ref == f"kv/users/{user.id}/{second.id}?version=1"
    assert ByokOut.of(second).previous_key_valid_until is not None
    second.previous_secret_valid_until = second.created_at  # long past
    assert await purge_replaced_keys(db, writer) == 1  # type: ignore[arg-type]
    await byok.remove_key(db, CTX, writer, second)  # type: ignore[arg-type]
    assert writer.deleted == [f"users/{user.id}/{second.id}"]


@respx.mock
async def test_a_key_that_does_not_work_is_not_stored(db: AsyncSession) -> None:
    respx.get(f"{ENDPOINT}/models").respond(401)
    user, writer = await _user(db), DeletingWriter()
    with pytest.raises(ProviderError, match="did not work"):
        await byok.add_key(db, CTX, writer, user.id, _input())  # type: ignore[arg-type]
    assert writer.stored == {}


@pytest.mark.parametrize(
    ("endpoint", "reason"),
    [
        ("https://10.1.2.3/v1", "private network"),
        ("http://1.1.1.1/v1", "https"),
        (None, "endpoint is needed"),
    ],
)
async def test_internal_endpoints_are_refused(
    db: AsyncSession, endpoint: str | None, reason: str
) -> None:
    user, writer = await _user(db), DeletingWriter()
    with respx.mock(assert_all_called=False) as mock:
        with pytest.raises(ProviderError, match=reason):
            await byok.add_key(db, CTX, writer, user.id, _input(endpoint=endpoint))  # type: ignore[arg-type]
        assert not mock.calls, "nothing is sent to a refused endpoint"
    assert writer.stored == {}
