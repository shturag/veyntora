"""Chatbots, their pipeline versions, attached sources, data rules and access.

Shared by the admin API and the CLI. Configuration changes go through ConfigService.
Pipeline versions are immutable once published: the current draft is edited, publishing
makes it live and starts a new draft, rollback makes an earlier version live again.
Roles per chatbot live in OpenFGA only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import Capability, Hosting
from veyntora_spec.filters import FilterError, parse_filter
from veyntora_spec.pipeline import FlowNodeType, PipelineSpec

from veyntora_api.authz.fga import PLATFORM, Authz, Tuple
from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService, VersionConflictError
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.automations import Automation
from veyntora_api.db.models.channels import Channel
from veyntora_api.db.models.chatbots import Chatbot, ChatbotStatus, PipelineStatus, PipelineVersion
from veyntora_api.db.models.conversations import Conversation
from veyntora_api.db.models.governance import GovernanceRule
from veyntora_api.db.models.identity import Group, User
from veyntora_api.db.models.knowledge import DataSource, IngestJobKind, SourceAttachment
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.db.models.tools import McpServer, McpServerStatus, Tool, ToolAccess
from veyntora_api.evaluation import service as evaluation
from veyntora_api.governance import service as governance
from veyntora_api.knowledge.service import enqueue
from veyntora_api.providers.service import with_fallbacks
from veyntora_api.secrets.openbao import SecretWriter

Role = Literal["owner", "editor", "approver", "user"]
ROLES: tuple[Role, ...] = ("owner", "editor", "approver", "user")


class ChatbotError(ValueError):
    pass


class ChatbotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    welcome_message: str = Field(default="", max_length=2000)
    answer_language: str = Field(default="auto", max_length=16)


class ChatbotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    welcome_message: str | None = Field(default=None, max_length=2000)
    answer_language: str | None = Field(default=None, max_length=16)
    status: Literal["live", "paused", "archived"] | None = None


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    # Scores of this source's passages are multiplied by this (boost or lower).
    weight: float = Field(1.0, gt=0, le=10)
    enabled: bool = True
    # Only documents under these folders (path prefixes); empty means the whole source.
    paths: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("paths")
    @classmethod
    def _folders(cls, v: list[str]) -> list[str]:
        out = []
        for raw in v:
            folder = raw.strip()
            if not folder:
                continue
            if len(folder) > 512 or ".." in folder:
                raise ValueError("folders are paths like /Policies/SLAs")
            out.append("/" + folder.strip("/"))
        return sorted(set(out))


class GovernanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_retention_days: int = Field(90, ge=1, le=3650)
    trace_retention_days: int = Field(30, ge=1, le=3650)
    allowed_external_instance_ids: list[UUID] = Field(default_factory=list)
    allowed_external_mcp_server_ids: list[UUID] = Field(default_factory=list)
    allow_byok: bool = False
    # Traces to Langfuse when it is external (Integrations); masked there regardless.
    allow_external_traces: bool = False
    # General chat without documents (unchecked answers, labelled as such).
    allow_no_documents: bool = False
    mask_pii_before_external: bool = True


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "user:<uuid>" or "group:<uuid>"
    principal: str = Field(pattern=r"^(user|group):[0-9a-f-]{36}$")
    role: Role


def chatbot_ref(bot_id: UUID) -> str:
    return f"chatbot:{bot_id}"


# ---------------------------------------------------------------- chatbots


async def create_chatbot(
    db: AsyncSession, ctx: RequestContext, authz: Authz, data: ChatbotInput, owner_id: UUID | None
) -> Chatbot:
    if await db.scalar(sa.select(Chatbot.id).where(Chatbot.slug == data.slug)):
        raise ChatbotError(f"the address {data.slug!r} is already taken")
    bot = Chatbot(**data.model_dump(), status=ChatbotStatus.DRAFT, owner_id=owner_id)
    await ConfigService(db, ctx).create(bot, action="chatbot.create")
    db.add(
        PipelineVersion(
            chatbot_id=bot.id,
            number=1,
            spec=PipelineSpec().model_dump(mode="json"),
            status=PipelineStatus.DRAFT,
            created_by=owner_id,
        )
    )
    await db.flush()
    # Written before the caller commits: a tuple for a row that never committed is harmless,
    # a committed chatbot without tuples would be unreachable.
    writes = [Tuple(PLATFORM, "platform", chatbot_ref(bot.id))]
    if owner_id is not None:
        writes.append(Tuple(f"user:{owner_id}", "owner", chatbot_ref(bot.id)))
    await authz.write(writes)
    return bot


async def update_chatbot(
    db: AsyncSession,
    ctx: RequestContext,
    bot: Chatbot,
    data: ChatbotUpdate,
    expected_version: int | None,
) -> Chatbot:
    if data.status == "live" and bot.live_version_id is None:
        raise ChatbotError("publish a pipeline version before going live")
    return await ConfigService(db, ctx).update(
        bot, data, expected_version=expected_version, action="chatbot.update"
    )


async def delete_chatbot(
    db: AsyncSession,
    ctx: RequestContext,
    authz: Authz,
    secrets: SecretWriter | None,
    bot: Chatbot,
) -> int:
    """Delete an archived chatbot for good: its chats, channels, data rule and settings.

    Refused while a legal hold covers the chatbot or anyone who chatted with it, and while
    an automation still uses it. Audit entries stay (they are the record that it existed).
    Returns the number of chats deleted.
    """
    if bot.status is not ChatbotStatus.ARCHIVED:
        raise ChatbotError("archive the chatbot first; only archived chatbots can be deleted")
    held_users, held_bots = await governance.held(db)
    if bot.id in held_bots:
        raise ChatbotError("a legal hold covers this chatbot")
    chatters = set(
        (
            await db.execute(
                sa.select(Conversation.user_id).where(Conversation.chatbot_id == bot.id).distinct()
            )
        ).scalars()
    )
    if chatters & held_users:
        raise ChatbotError("a legal hold covers chats of people who used this chatbot")
    text = str(bot.id)
    automations = (
        (
            await db.execute(
                sa.select(Automation.name)
                .where(
                    sa.or_(
                        Automation.chatbot_id == bot.id,
                        sa.cast(Automation.spec, sa.Text).contains(text),
                    )
                )
                .order_by(Automation.name)
            )
        )
        .scalars()
        .all()
    )
    if automations:
        raise ChatbotError(f"used by the automations {', '.join(automations)}: change them first")
    chats = await db.scalar(
        sa.select(sa.func.count())
        .select_from(Conversation)
        .where(Conversation.chatbot_id == bot.id)
    )
    # Teams and Slack channels keep their app secrets in OpenBao; those go with them.
    keyed = list(
        (
            await db.execute(
                sa.select(Channel.id).where(
                    Channel.chatbot_id == bot.id, Channel.secret_ref.is_not(None)
                )
            )
        ).scalars()
    )
    if keyed and secrets is None:
        raise ChatbotError("the secret store is not available")
    await ConfigService(db, ctx).delete(bot, action="chatbot.delete")
    for channel_id in keyed:
        await secrets.delete(f"channels/{channel_id}")  # type: ignore[union-attr]
    # Permissions last, before the caller commits: if this fails the transaction rolls
    # back and the chatbot stays, archived.
    tuples = await authz.read(f"chatbot:{bot.id}")
    if tuples:
        await authz.write(deletes=tuples)
    await audit.record(
        db,
        ctx,
        action="chatbot.chats_deleted",
        target_type="chatbot",
        target_id=str(bot.id),
        after={"chats": int(chats or 0)},
    )
    return int(chats or 0)


async def draft_of(db: AsyncSession, bot: Chatbot) -> PipelineVersion:
    draft = await db.scalar(
        sa.select(PipelineVersion).where(
            PipelineVersion.chatbot_id == bot.id, PipelineVersion.status == PipelineStatus.DRAFT
        )
    )
    if draft is None:
        raise ChatbotError("this chatbot has no draft")
    return draft


async def _next_number(db: AsyncSession, bot_id: UUID) -> int:
    current = await db.scalar(
        sa.select(sa.func.max(PipelineVersion.number)).where(PipelineVersion.chatbot_id == bot_id)
    )
    return int(current or 0) + 1


# ---------------------------------------------------------------- pipeline checks


_EXPECTED: dict[str, Capability] = {
    "ingestion.parser_instance_id": Capability.PARSER,
    "ingestion.embedding_instance_id": Capability.EMBEDDING,
    "retrieval.vector_store_instance_id": Capability.VECTOR_STORE,
    "retrieval.embedding_instance_id": Capability.EMBEDDING,
    "rerank.reranker_instance_id": Capability.RERANKER,
    "rerank.fallback_instance_id": Capability.RERANKER,
    "generation.llm_instance_id": Capability.LLM,
    "agent.llm_instance_id": Capability.LLM,
    "router.router_instance_id": Capability.LLM,
    "guardrails.input_guardrail_instance_id": Capability.GUARDRAIL,
    "guardrails.output_guardrail_instance_id": Capability.GUARDRAIL,
    "guardrails.pii_instance_id": Capability.GUARDRAIL,
}


# Slots that need a particular kind of provider within a capability. The PII slot finds
# personal data to mask, which a safety classifier such as Llama Guard cannot do.
PII_ADAPTERS = frozenset({"azure_pii"})
_ADAPTERS: dict[str, frozenset[str]] = {"guardrails.pii_instance_id": PII_ADAPTERS}


def instance_refs(spec: PipelineSpec) -> dict[str, UUID]:
    out: dict[str, UUID] = {}
    for path in _EXPECTED:
        section, field = path.split(".")
        value = getattr(getattr(spec, section), field)
        if value is not None:
            out[path] = value
    return out


async def reference_problems(
    db: AsyncSession, spec: PipelineSpec
) -> tuple[list[str], dict[UUID, ProviderInstance]]:
    refs = instance_refs(spec)
    rows = {
        p.id: p
        for p in (
            await db.execute(
                sa.select(ProviderInstance).where(ProviderInstance.id.in_(set(refs.values())))
            )
        ).scalars()
    }
    problems = []
    for path, ref in refs.items():
        row = rows.get(ref)
        if row is None:
            problems.append(f"{path} points to a provider that does not exist")
        elif row.capability is not _EXPECTED[path]:
            problems.append(f"{path} needs a {_EXPECTED[path].value} provider, not {row.name}")
        elif path in _ADAPTERS and row.adapter not in _ADAPTERS[path]:
            problems.append(
                f"{path} needs a personal-data detector (Azure AI Language PII); "
                f"{row.name} is a safety check: use it as the input or output safety check"
            )
        elif not row.enabled:
            problems.append(f"{path}: provider {row.name} is disabled")
    return problems, rows


async def external_problems(
    db: AsyncSession, bot: Chatbot, rows: dict[UUID, ProviderInstance], spec: PipelineSpec
) -> list[str]:
    """Data stays in-house unless a data rule allows this external provider for this bot.

    Fallback providers count too. When the rule asks for masking, external models are
    allowed once the pipeline has a PII provider; that provider is the masker and is exempt
    from masking itself.
    """
    rows = await with_fallbacks(db, rows)
    rule = await db.scalar(sa.select(GovernanceRule).where(GovernanceRule.chatbot_id == bot.id))
    allowed = set(rule.allowed_external_instance_ids) if rule else set()
    masker = spec.guardrails.pii_instance_id
    platform = await governance.settings_of(db)
    must_mask = platform.require_mask_before_external or bool(
        rule and rule.mask_pii_before_external
    )
    problems = await governance.external_problems(db, list(rows.values()))
    for p in rows.values():
        if p.hosting is not Hosting.EXTERNAL:
            continue
        if p.id not in allowed:
            problems.append(
                f"{p.name} is an external provider; allow it in this chatbot's data rules first"
            )
        elif must_mask and p.id != masker and masker is None:
            problems.append(
                f"the data rule asks to mask personal data before {p.name}; choose a PII "
                "provider on the Guardrails page, or switch the rule off"
            )
    return problems


def flow_tool_ids(spec: PipelineSpec) -> list[UUID]:
    """Tools a custom flow uses: agent toolboxes and direct tool steps."""
    if not spec.flow.custom:
        return []
    out: list[UUID] = []
    for n in spec.flow.nodes:
        if n.type is FlowNodeType.MCP_TOOL:
            ids = [n.config.get("tool_id"), *(n.config.get("tool_ids") or [])]
            out += [UUID(str(i)) for i in ids if i]
    return out


async def flow_approval_problems(db: AsyncSession, spec: PipelineSpec) -> list[str]:
    """No write without approval: a direct step calling a write tool comes right after a
    human approval step (every way into it)."""
    if not spec.flow.custom:
        return []
    kinds = {n.id: n.type for n in spec.flow.nodes}
    problems = []
    for n in spec.flow.nodes:
        tool_id = n.config.get("tool_id") if n.type is FlowNodeType.MCP_TOOL else None
        if not tool_id:
            continue
        try:
            tool = await db.get(Tool, UUID(str(tool_id)))
        except ValueError:
            tool = None
        if tool is None:
            continue  # reported by tool_problems
        incoming = [e.source for e in spec.flow.edges if e.target == n.id]
        approved = incoming and all(kinds[s] is FlowNodeType.HUMAN_APPROVAL for s in incoming)
        if tool.access is not ToolAccess.READ and not approved:
            problems.append(
                f"{n.label or n.id}: {tool.name} writes; put a human approval step before it"
            )
    return problems


async def tool_problems(db: AsyncSession, bot: Chatbot, spec: PipelineSpec) -> list[str]:
    """Bound tools must be usable; an external MCP server needs the chatbot's data rule."""
    bound = [b.tool_id for b in spec.agent.tools if b.enabled] + flow_tool_ids(spec)
    if not bound:
        return []
    rows = {
        t.id: (t, server)
        for t, server in (
            await db.execute(
                sa.select(Tool, McpServer)
                .join(McpServer, McpServer.id == Tool.server_id)
                .where(Tool.id.in_(bound))
            )
        ).all()
    }
    rule = await db.scalar(sa.select(GovernanceRule).where(GovernanceRule.chatbot_id == bot.id))
    allowed = set(rule.allowed_external_mcp_server_ids) if rule else set()
    problems = []
    for tool_id in bound:
        found = rows.get(tool_id)
        if found is None:
            problems.append(f"agent tool {tool_id} no longer exists")
            continue
        tool, server = found
        if not tool.enabled or tool.access is ToolAccess.DESTRUCTIVE:
            problems.append(f"agent tool {tool.name} is not enabled")
        elif server.status is not McpServerStatus.ACTIVE:
            problems.append(f"agent tool {tool.name}: server {server.name} is not active")
        elif server.hosting == "external" and server.id not in allowed:
            problems.append(
                f"{server.name} is an external MCP server; allow it in this chatbot's data rules"
            )
    return problems


async def save_draft(
    db: AsyncSession,
    ctx: RequestContext,
    bot: Chatbot,
    spec: PipelineSpec,
    *,
    expected_version: int | None,
    change_note: str = "",
) -> PipelineVersion:
    """Replace the draft spec. The chatbot's version guards against concurrent editors."""
    try:
        parse_filter(spec.retrieval.metadata_filter)
    except FilterError as exc:
        raise ChatbotError(f"metadata filter: {exc}") from exc
    problems, _ = await reference_problems(db, spec)
    if problems:
        raise ChatbotError("; ".join(problems))
    if expected_version is not None and bot.version != expected_version:
        raise VersionConflictError("chatbot", str(bot.id), expected_version, bot.version)
    draft = await draft_of(db, bot)
    before = draft.spec
    after = spec.model_dump(mode="json")
    if before == after and draft.change_note == change_note:
        return draft
    draft.spec = after
    draft.change_note = change_note
    bot.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="pipeline.draft_update",
        target_type="pipeline_version",
        target_id=str(draft.id),
        before={"spec": before},
        after={"spec": after, "chatbot_version": bot.version},
    )
    await _sync_attached_sources(db, bot.id, None)
    return draft


async def publish_problems(db: AsyncSession, bot: Chatbot, *, gate: bool = True) -> list[str]:
    draft = await draft_of(db, bot)
    spec = PipelineSpec.model_validate(draft.spec)
    problems = spec.publish_problems()
    if not spec.retrieval.enabled:
        rule = await db.scalar(sa.select(GovernanceRule).where(GovernanceRule.chatbot_id == bot.id))
        if not (rule and rule.allow_no_documents):
            problems.append(
                "answering without documents needs this chatbot's data rule to allow it"
            )
    ref_problems, rows = await reference_problems(db, spec)
    return (
        problems
        + ref_problems
        + await external_problems(db, bot, rows, spec)
        + await tool_problems(db, bot, spec)
        + await flow_approval_problems(db, spec)
        + (await evaluation.gate_problems(db, bot) if gate else [])
    )


async def publish(
    db: AsyncSession, ctx: RequestContext, bot: Chatbot, triggered_by: UUID | None
) -> PipelineVersion:
    if problems := await publish_problems(db, bot):
        raise ChatbotError("; ".join(problems))
    draft = await draft_of(db, bot)
    previous = await db.get(PipelineVersion, bot.live_version_id) if bot.live_version_id else None
    if previous is not None:
        previous.status = PipelineStatus.ARCHIVED
    draft.status = PipelineStatus.LIVE
    draft.published_at = datetime.now(UTC)
    bot.live_version_id = draft.id
    if bot.status is ChatbotStatus.DRAFT:
        bot.status = ChatbotStatus.LIVE
    bot.version += 1
    db.add(
        PipelineVersion(
            chatbot_id=bot.id,
            number=await _next_number(db, bot.id),
            spec=draft.spec,
            status=PipelineStatus.DRAFT,
            created_by=triggered_by,
        )
    )
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="pipeline.publish",
        target_type="chatbot",
        target_id=str(bot.id),
        before={"live_version": previous.number if previous else None},
        after={"live_version": draft.number, "version_id": str(draft.id)},
    )
    await _sync_attached_sources(db, bot.id, triggered_by)
    return draft


async def rollback(
    db: AsyncSession, ctx: RequestContext, bot: Chatbot, number: int, triggered_by: UUID | None
) -> PipelineVersion:
    """Make an earlier published version live again (the current draft is kept)."""
    target = await db.scalar(
        sa.select(PipelineVersion).where(
            PipelineVersion.chatbot_id == bot.id, PipelineVersion.number == number
        )
    )
    if target is None or target.published_at is None:
        raise ChatbotError(f"version {number} was never published")
    if target.id == bot.live_version_id:
        return target
    target_spec = PipelineSpec.model_validate(target.spec)
    _, rows = await reference_problems(db, target_spec)
    if problems := await external_problems(db, bot, rows, target_spec):
        raise ChatbotError("; ".join(problems))
    previous = await db.get(PipelineVersion, bot.live_version_id) if bot.live_version_id else None
    if previous is not None:
        previous.status = PipelineStatus.ARCHIVED
    target.status = PipelineStatus.LIVE
    bot.live_version_id = target.id
    bot.version += 1
    await db.flush()
    await audit.record(
        db,
        ctx,
        action="pipeline.rollback",
        target_type="chatbot",
        target_id=str(bot.id),
        before={"live_version": previous.number if previous else None},
        after={"live_version": target.number},
    )
    await _sync_attached_sources(db, bot.id, triggered_by)
    return target


# ---------------------------------------------------------------- sources


async def _sync_attached_sources(db: AsyncSession, bot_id: UUID, triggered_by: UUID | None) -> None:
    """Index attached sources into any profile the bot's versions now need."""
    source_ids = (
        await db.execute(
            sa.select(SourceAttachment.source_id).where(
                SourceAttachment.chatbot_id == bot_id, SourceAttachment.enabled.is_(True)
            )
        )
    ).scalars()
    for source_id in source_ids:
        await enqueue(db, source_id, IngestJobKind.SYNC, triggered_by=triggered_by)


async def set_sources(
    db: AsyncSession,
    ctx: RequestContext,
    bot: Chatbot,
    items: list[Attachment],
    triggered_by: UUID | None,
) -> list[SourceAttachment]:
    wanted = {i.source_id: i for i in items}
    if len(wanted) != len(items):
        raise ChatbotError("a source is listed twice")
    if wanted:
        found = set(
            (await db.execute(sa.select(DataSource.id).where(DataSource.id.in_(wanted)))).scalars()
        )
        if missing := [str(s) for s in wanted if s not in found]:
            raise ChatbotError(f"unknown sources: {', '.join(missing)}")
    svc = ConfigService(db, ctx)
    current = {
        a.source_id: a
        for a in (
            await db.execute(
                sa.select(SourceAttachment).where(SourceAttachment.chatbot_id == bot.id)
            )
        ).scalars()
    }
    for source_id, old in current.items():
        if source_id not in wanted:
            await svc.delete(old, action="chatbot.source_detach")
    for source_id, item in wanted.items():
        row = current.get(source_id)
        if row is None:
            await svc.create(
                SourceAttachment(
                    chatbot_id=bot.id,
                    source_id=source_id,
                    weight=item.weight,
                    enabled=item.enabled,
                    scope={"paths": item.paths},
                ),
                action="chatbot.source_attach",
            )
        else:
            await svc.update(
                row,
                {"weight": item.weight, "enabled": item.enabled, "scope": {"paths": item.paths}},
                action="chatbot.source_update",
            )
        if item.enabled:
            await enqueue(db, source_id, IngestJobKind.SYNC, triggered_by=triggered_by)
    return list(
        (
            await db.execute(
                sa.select(SourceAttachment).where(SourceAttachment.chatbot_id == bot.id)
            )
        ).scalars()
    )


# ---------------------------------------------------------------- governance


async def set_governance(
    db: AsyncSession, ctx: RequestContext, bot: Chatbot, data: GovernanceInput
) -> GovernanceRule:
    ids = set(data.allowed_external_instance_ids)
    if ids:
        rows = (
            await db.execute(sa.select(ProviderInstance).where(ProviderInstance.id.in_(ids)))
        ).scalars()
        by_id = {r.id: r for r in rows}
        for i in ids:
            row = by_id.get(i)
            if row is None:
                raise ChatbotError(f"unknown provider {i}")
            if row.hosting is not Hosting.EXTERNAL:
                raise ChatbotError(f"{row.name} is self-hosted; only external providers are listed")
        if eu := await governance.external_problems(db, list(by_id.values())):
            raise ChatbotError("; ".join(eu))
    platform = await governance.settings_of(db)
    if platform.require_mask_before_external and not data.mask_pii_before_external:
        raise ChatbotError("the platform requires masking personal data before external providers")
    servers = set(data.allowed_external_mcp_server_ids)
    for server_id in servers:
        server = await db.get(McpServer, server_id)
        if server is None:
            raise ChatbotError(f"unknown MCP server {server_id}")
        if server.hosting != "external":
            raise ChatbotError(
                f"{server.name} runs inside the network; only external ones are listed"
            )
    values: dict[str, Any] = data.model_dump()
    values["allowed_external_instance_ids"] = sorted(ids, key=str)
    values["allowed_external_mcp_server_ids"] = sorted(servers, key=str)
    svc = ConfigService(db, ctx)
    rule = await db.scalar(sa.select(GovernanceRule).where(GovernanceRule.chatbot_id == bot.id))
    if rule is None:
        return await svc.create(
            GovernanceRule(chatbot_id=bot.id, **values), action="governance.create"
        )
    return await svc.update(rule, values, action="governance.update")


# ---------------------------------------------------------------- access


def _subject(principal: str) -> str:
    kind, _, ident = principal.partition(":")
    return f"group:{ident}#member" if kind == "group" else principal


def _principal(subject: str) -> str:
    return subject.removesuffix("#member")


async def read_access(authz: Authz, bot_id: UUID) -> list[Grant]:
    tuples = await authz.read(chatbot_ref(bot_id))
    return [
        Grant.model_validate({"principal": _principal(t.user), "role": t.relation})
        for t in tuples
        if t.relation in ROLES
    ]


async def set_access(
    db: AsyncSession, ctx: RequestContext, authz: Authz, bot: Chatbot, grants: list[Grant]
) -> list[Grant]:
    users = {UUID(g.principal[5:]) for g in grants if g.principal.startswith("user:")}
    groups = {UUID(g.principal[6:]) for g in grants if g.principal.startswith("group:")}
    if users:
        found = set((await db.execute(sa.select(User.id).where(User.id.in_(users)))).scalars())
        if missing := users - found:
            raise ChatbotError(f"unknown users: {', '.join(map(str, missing))}")
    if groups:
        found = set((await db.execute(sa.select(Group.id).where(Group.id.in_(groups)))).scalars())
        if missing := groups - found:
            raise ChatbotError(f"unknown groups: {', '.join(map(str, missing))}")
    if not any(g.role == "owner" for g in grants):
        raise ChatbotError("a chatbot needs at least one owner")

    current = {(g.principal, g.role) for g in await read_access(authz, bot.id)}
    wanted = {(g.principal, g.role) for g in grants}
    obj = chatbot_ref(bot.id)
    await audit.record(
        db,
        ctx,
        action="chatbot.access_update",
        target_type="chatbot",
        target_id=str(bot.id),
        before={"grants": sorted(f"{r}:{p}" for p, r in current)},
        after={"grants": sorted(f"{r}:{p}" for p, r in wanted)},
    )
    await authz.write(
        writes=[Tuple(_subject(p), r, obj) for p, r in wanted - current],
        deletes=[Tuple(_subject(p), r, obj) for p, r in current - wanted],
    )
    return [Grant(principal=p, role=r) for p, r in sorted(wanted)]
