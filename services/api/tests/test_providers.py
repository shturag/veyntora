from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.core.context import Actor, RequestContext
from veyntora_api.db.models.chatbots import (
    Chatbot,
    ChatbotStatus,
    PipelineStatus,
    PipelineVersion,
)
from veyntora_api.db.models.governance import ActorType, AuditEvent
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.providers.service import (
    ProviderError,
    ProviderInput,
    ProviderUpdate,
    create_provider,
    pipelines_using,
    purge_replaced_keys,
    set_secret,
    update_provider,
)
from veyntora_api.routers.admin_providers import ProviderOut
from veyntora_api.secrets.openbao import SecretRef, last4
from veyntora_providers.interfaces import Capability, Hosting

CTX = RequestContext(actor=Actor(ActorType.USER, "u-admin", "Admin"))
KEY = "sk-ant-api03-0123456789abcdefWXYZ"


class FakeWriter:
    def __init__(self) -> None:
        self.stored: dict[str, str] = {}
        self.versions: dict[str, int] = {}
        self.destroyed: list[str] = []

    async def put(self, path: str, value: str, expires_at: datetime | None = None) -> SecretRef:
        self.stored[path] = value
        self.versions[path] = self.versions.get(path, 0) + 1
        return SecretRef(
            ref=f"kv/{path}",
            last4=last4(value),
            expires_at=expires_at,
            version=self.versions[path],
        )

    async def destroy_version(self, ref: str) -> None:
        self.destroyed.append(ref)

    async def delete(self, path: str) -> None:
        self.stored.pop(path, None)
        self.destroyed.append(path)


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
    assert rotation.after == {"secret_last4": "QRST", "secret_expires_at": None, "grace": "24h"}


async def test_replaced_key_keeps_working_for_the_grace_period(db: AsyncSession) -> None:
    writer = FakeWriter()
    row = await create_provider(db, CTX, writer, _input(name="Claude G", secret=SecretStr(KEY)))
    assert row.previous_secret_ref is None, "a first key replaces nothing"
    await set_secret(db, CTX, writer, row, value=SecretStr(KEY + "2"), expires_at=None)
    assert row.previous_secret_ref == f"kv/providers/{row.id}?version=1"
    assert row.previous_secret_valid_until is not None
    left = row.previous_secret_valid_until - datetime.now(UTC)
    assert timedelta(hours=23) < left <= timedelta(hours=24)
    out = ProviderOut.of(row)
    assert out.previous_key_valid_until == row.previous_secret_valid_until
    assert "version=" not in out.model_dump_json()

    # Replacing again: only one earlier key is kept.
    await set_secret(db, CTX, writer, row, value=SecretStr(KEY + "3"), expires_at=None, grace="1h")
    assert writer.destroyed == [f"kv/providers/{row.id}?version=1"]
    assert row.previous_secret_ref == f"kv/providers/{row.id}?version=2"

    # "now" destroys the replaced key at once.
    await set_secret(db, CTX, writer, row, value=SecretStr(KEY + "4"), expires_at=None, grace="now")
    assert writer.destroyed[-2:] == [
        f"kv/providers/{row.id}?version=2",
        f"kv/providers/{row.id}?version=3",
    ]
    assert row.previous_secret_ref is None and row.previous_secret_valid_until is None
    with pytest.raises(ProviderError, match="grace period"):
        await set_secret(
            db, CTX, writer, row, value=SecretStr(KEY), expires_at=None, grace="forever"
        )


async def test_expired_grace_periods_are_purged(db: AsyncSession) -> None:
    writer = FakeWriter()
    row = await create_provider(db, CTX, writer, _input(name="Claude P", secret=SecretStr(KEY)))
    await set_secret(db, CTX, writer, row, value=SecretStr(KEY + "2"), expires_at=None)
    assert await purge_replaced_keys(db, writer) == 0  # type: ignore[arg-type]
    row.previous_secret_valid_until = datetime.now(UTC) - timedelta(minutes=1)
    assert await purge_replaced_keys(db, writer) == 1  # type: ignore[arg-type]
    assert writer.destroyed == [f"kv/providers/{row.id}?version=1"]
    assert row.previous_secret_ref is None


async def test_fallbacks_must_match_and_not_loop(db: AsyncSession) -> None:
    a = await create_provider(db, CTX, None, _input(name="LLM A"))
    b = await create_provider(db, CTX, None, _input(name="LLM B"))
    embed = await create_provider(
        db,
        CTX,
        None,
        _input(name="Embed", capability=Capability.EMBEDDING, adapter="voyage", model="v"),
    )
    with pytest.raises(ProviderError, match="same capability"):
        await update_provider(db, CTX, a, ProviderUpdate(fallback_instance_id=embed.id), None)
    await update_provider(db, CTX, a, ProviderUpdate(fallback_instance_id=b.id), None)
    with pytest.raises(ProviderError, match="loop"):
        await update_provider(db, CTX, b, ProviderUpdate(fallback_instance_id=a.id), None)
    with pytest.raises(ProviderError, match="loop"):
        await update_provider(db, CTX, a, ProviderUpdate(fallback_instance_id=a.id), None)


async def test_a_provider_in_use_is_disabled_only_with_a_replacement(db: AsyncSession) -> None:
    from tests.test_ingestion import World  # noqa: PLC0415

    w = await World(db).setup()
    llm = await db.get(ProviderInstance, w.llm)
    assert llm is not None
    bot = Chatbot(slug=f"b-{llm.id.hex[:6]}", name="Support", status=ChatbotStatus.DRAFT)
    db.add(bot)
    await db.flush()
    db.add(
        PipelineVersion(
            chatbot_id=bot.id,
            number=1,
            status=PipelineStatus.DRAFT,
            spec=w.spec().model_dump(mode="json"),
        )
    )
    await db.flush()
    assert await pipelines_using(db, llm.id) == ["Support"]
    with pytest.raises(ProviderError, match="in use by Support"):
        await update_provider(db, CTX, llm, ProviderUpdate(enabled=False), None)

    spare = await create_provider(db, CTX, None, _input(name="Spare LLM"))
    await update_provider(
        db, CTX, llm, ProviderUpdate(enabled=False, fallback_instance_id=spare.id), None
    )
    assert llm.enabled is False
    # The stand-in cannot be disabled or removed while it stands in.
    with pytest.raises(ProviderError, match="via"):
        await update_provider(db, CTX, spare, ProviderUpdate(enabled=False), None)
    with pytest.raises(ProviderError, match="in use"):
        await update_provider(db, CTX, llm, ProviderUpdate(fallback_instance_id=None), None)


async def test_duplicate_names_are_rejected(db: AsyncSession) -> None:
    await create_provider(db, CTX, None, _input(name="Claude C"))
    with pytest.raises(ProviderError, match="already exists"):
        await create_provider(db, CTX, None, _input(name="Claude C"))


def test_endpoints_are_base_urls() -> None:
    with pytest.raises(ValueError, match=r"base URL \(https://api.example.com/v1\)"):
        _input(adapter="openai_compatible", endpoint="https://api.example.com/v1/chat/completions")
    with pytest.raises(ValueError, match="without /embeddings"):
        ProviderUpdate(endpoint="https://api.example.com/v1/embeddings/")
    assert ProviderUpdate(endpoint="https://api.example.com/v1/").endpoint == (
        "https://api.example.com/v1"
    )


async def test_hosting_can_be_corrected_but_vendor_apis_stay_external(db: AsyncSession) -> None:
    row = await create_provider(
        db,
        CTX,
        None,
        _input(
            capability=Capability.EMBEDDING,
            adapter="openai_compatible",
            name="Cloud embeddings",
            endpoint="https://api.example.com/v1",
            hosting=Hosting.SELF_HOSTED,
        ),
    )
    await update_provider(
        db, CTX, row, ProviderUpdate(hosting=Hosting.EXTERNAL, region="eu-central"), None
    )
    assert (row.hosting, row.region) == (Hosting.EXTERNAL, "eu-central")
    claude = await create_provider(db, CTX, None, _input())
    with pytest.raises(ProviderError, match="must stay external"):
        await update_provider(db, CTX, claude, ProviderUpdate(hosting=Hosting.SELF_HOSTED), None)


async def test_the_pii_slot_takes_only_a_personal_data_detector(db: AsyncSession) -> None:
    from veyntora_api.chatbots.service import reference_problems  # noqa: PLC0415
    from veyntora_spec.pipeline import PipelineSpec  # noqa: PLC0415

    guard = await create_provider(
        db,
        CTX,
        None,
        _input(
            capability=Capability.GUARDRAIL,
            adapter="llama_guard",
            name="Llama Guard",
            endpoint="https://guard.example.com/v1",
            model="meta-llama/Llama-Guard-4-12B",
        ),
    )
    spec = PipelineSpec()
    spec.guardrails.input_guardrail_instance_id = guard.id
    assert (await reference_problems(db, spec))[0] == []
    spec.guardrails.pii_instance_id = guard.id
    [problem] = (await reference_problems(db, spec))[0]
    assert "personal-data detector" in problem and "Llama Guard" in problem


async def test_presidio_fills_only_the_pii_slot(db: AsyncSession) -> None:
    from veyntora_api.chatbots.service import reference_problems  # noqa: PLC0415
    from veyntora_spec.pipeline import PipelineSpec  # noqa: PLC0415

    presidio = await create_provider(
        db,
        CTX,
        None,
        _input(
            capability=Capability.GUARDRAIL,
            adapter="presidio",
            name="Presidio",
            endpoint="http://presidio:3000",
            hosting=Hosting.SELF_HOSTED,
            model=None,
        ),
    )
    spec = PipelineSpec()
    spec.guardrails.pii_instance_id = presidio.id
    assert (await reference_problems(db, spec))[0] == []
    spec.guardrails.input_guardrail_instance_id = presidio.id
    [problem] = (await reference_problems(db, spec))[0]
    assert "needs a safety check" in problem and "Presidio" in problem


def test_pgvector_takes_a_database_address_without_its_password() -> None:
    from veyntora_api.providers.service import ProviderInput  # noqa: PLC0415

    base = {"capability": "vector_store", "name": "pg", "hosting": "self_hosted"}
    ok = ProviderInput.model_validate(
        {**base, "adapter": "pgvector", "endpoint": "postgresql://veyntora@db:5432/veyntora"}
    )
    assert ok.endpoint == "postgresql://veyntora@db:5432/veyntora"
    with pytest.raises(ValueError, match="secret, not in the address"):
        ProviderInput.model_validate(
            {**base, "adapter": "pgvector", "endpoint": "postgresql://u:hunter2@db/v"}
        )
    with pytest.raises(ValueError, match="postgresql://"):
        ProviderInput.model_validate({**base, "adapter": "pgvector", "endpoint": "http://db"})
    with pytest.raises(ValueError, match="http"):
        ProviderInput.model_validate(
            {**base, "adapter": "qdrant", "endpoint": "postgresql://veyntora@db/v"}
        )
