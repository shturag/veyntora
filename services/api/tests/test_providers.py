from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.core.context import Actor, RequestContext
from veyntora_api.db.models.governance import ActorType, AuditEvent
from veyntora_api.providers.service import ProviderError, ProviderInput, create_provider, set_secret
from veyntora_api.routers.admin_providers import ProviderOut
from veyntora_api.secrets.openbao import SecretRef, last4
from veyntora_providers.interfaces import Capability, Hosting

CTX = RequestContext(actor=Actor(ActorType.USER, "u-admin", "Admin"))
KEY = "sk-ant-api03-0123456789abcdefWXYZ"


class FakeWriter:
    def __init__(self) -> None:
        self.stored: dict[str, str] = {}

    async def put(self, path: str, value: str, expires_at: datetime | None = None) -> SecretRef:
        self.stored[path] = value
        return SecretRef(ref=f"kv/{path}", last4=last4(value), expires_at=expires_at)


def _input(**kw: object) -> ProviderInput:
    base: dict[str, object] = {
        "capability": Capability.LLM,
        "adapter": "anthropic",
        "name": "Claude",
        "model": "claude-opus-5-5",
        "hosting": Hosting.EXTERNAL,
    }
    return ProviderInput.model_validate({**base, **kw})


async def test_unknown_adapter_is_rejected(db: AsyncSession) -> None:
    with pytest.raises(ProviderError, match="unknown adapter"):
        await create_provider(db, CTX, None, _input(adapter="gpt-magic"))


async def test_vendor_adapters_must_be_marked_external(db: AsyncSession) -> None:
    with pytest.raises(ProviderError, match="must be marked external"):
        await create_provider(db, CTX, None, _input(hosting=Hosting.SELF_HOSTED))


async def test_key_goes_to_the_secret_store_and_nowhere_else(db: AsyncSession) -> None:
    writer = FakeWriter()
    expires = datetime(2027, 3, 1, tzinfo=UTC)
    row = await create_provider(
        db, CTX, writer, _input(name="Claude A", secret=SecretStr(KEY), secret_expires_at=expires)
    )
    assert writer.stored == {f"providers/{row.id}": KEY}
    assert row.secret_ref == f"kv/providers/{row.id}"
    assert row.secret_last4 == "WXYZ"

    out = ProviderOut.of(row).model_dump_json()
    assert KEY not in out
    assert "kv/providers" not in out, "the OpenBao path is not exposed either"
    assert '"has_secret":true' in out

    events = (
        (await db.execute(sa.select(AuditEvent).where(AuditEvent.target_id == str(row.id))))
        .scalars()
        .all()
    )
    assert {e.action for e in events} >= {"provider.create", "provider.secret_set"}
    for e in events:
        assert KEY not in str(e.before) and KEY not in str(e.after)


async def test_replacing_the_key_is_audited_as_rotation(db: AsyncSession) -> None:
    writer = FakeWriter()
    row = await create_provider(db, CTX, writer, _input(name="Claude B", secret=SecretStr(KEY)))
    await set_secret(
        db, CTX, writer, row, value=SecretStr(KEY.replace("WXYZ", "QRST")), expires_at=None
    )
    assert row.secret_last4 == "QRST"
    rotation = (
        await db.execute(
            sa.select(AuditEvent).where(
                AuditEvent.target_id == str(row.id), AuditEvent.action == "provider.secret_rotate"
            )
        )
    ).scalar_one()
    assert rotation.before == {"secret_last4": "WXYZ", "secret_expires_at": None}
    assert rotation.after == {"secret_last4": "QRST", "secret_expires_at": None}


async def test_duplicate_names_are_rejected(db: AsyncSession) -> None:
    await create_provider(db, CTX, None, _input(name="Claude C"))
    with pytest.raises(ProviderError, match="already exists"):
        await create_provider(db, CTX, None, _input(name="Claude C"))
