"""Which index profiles a source must be indexed into.

A source is indexed for every chatbot it is attached to (enabled attachments, chatbot not
archived), for the chatbot's live, canary and current draft pipeline versions, so that a
draft can be tested before it is published. External providers need the data rule first.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import Hosting
from veyntora_spec.pipeline import PipelineSpec
from veyntora_spec.profile import IndexProfile, index_profile

from veyntora_api.db.models.chatbots import (
    Chatbot,
    ChatbotStatus,
    PipelineStatus,
    PipelineVersion,
)
from veyntora_api.db.models.governance import GovernanceRule
from veyntora_api.db.models.knowledge import DataSource, SourceAttachment
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.knowledge.reading import extraction_of

log = structlog.get_logger()


def may_send(rule: GovernanceRule | None, provider: ProviderInstance | None) -> bool:
    """Whether a chatbot's data rule lets its documents reach this provider."""
    if provider is None or provider.hosting is not Hosting.EXTERNAL:
        return provider is not None
    return (
        rule is not None
        and provider.id in rule.allowed_external_instance_ids
        # Documents are not masked before embedding: an external parser or embedder needs
        # the masking rule switched off (fail closed).
        and not rule.mask_pii_before_external
    )


def _blocked(rule: GovernanceRule | None, provider: ProviderInstance) -> str:
    if rule is not None and provider.id in rule.allowed_external_instance_ids:
        return (
            f"{provider.name} is external and the data rule masks personal data before "
            "external providers, which documents cannot be (they are embedded as they are): "
            "use a self-hosted model, or switch that masking off"
        )
    return f"the data rule does not allow the external provider {provider.name}"


async def index_plan(db: AsyncSession, source_id: UUID) -> tuple[list[IndexProfile], str | None]:
    """Profiles the source must be indexed into, and why there are none (for people).

    A profile whose parser, vision model, embedding or vector store is an external provider is
    only used if the chatbot's data rule allows that provider: documents are sent to it during
    indexing, long before anyone asks a question, and drafts are indexed too.
    """
    source = await db.get(DataSource, source_id)
    if source is None:
        return [], "the source no longer exists"
    personal = source.uploaded_by is not None
    if personal:
        # "My files" are searched by every chat of their owner: index them for the live
        # chatbots. Only their owner can read the chunks.
        query = sa.select(Chatbot).where(Chatbot.status == ChatbotStatus.LIVE)
    else:
        query = (
            sa.select(Chatbot)
            .join(SourceAttachment, SourceAttachment.chatbot_id == Chatbot.id)
            .where(
                SourceAttachment.source_id == source_id,
                SourceAttachment.enabled.is_(True),
                Chatbot.status != ChatbotStatus.ARCHIVED,
            )
        )
    bots = (await db.execute(query)).scalars().all()
    if not bots:
        return [], "no chatbot uses this source: attach it under a chatbot's Knowledge"
    names = {b.id: b.name for b in bots}
    bot_ids = [b.id for b in bots]
    published = {v for b in bots for v in (b.live_version_id, b.canary_version_id) if v}
    drafts = sa.false() if personal else PipelineVersion.status == PipelineStatus.DRAFT
    versions = (
        await db.execute(
            sa.select(PipelineVersion.chatbot_id, PipelineVersion.spec).where(
                PipelineVersion.chatbot_id.in_(bot_ids),
                sa.or_(PipelineVersion.id.in_(published), drafts),
            )
        )
    ).all()
    rules = {
        r.chatbot_id: r
        for r in (
            await db.execute(
                sa.select(GovernanceRule).where(GovernanceRule.chatbot_id.in_(bot_ids))
            )
        ).scalars()
    }
    candidates: list[tuple[UUID, IndexProfile]] = []
    for chatbot_id, raw in versions:
        try:
            # The source's own reading (ADR 0040); "My files" read as the pipeline says.
            profile = index_profile(
                PipelineSpec.model_validate(raw), None if personal else extraction_of(source)
            )
        except ValidationError:
            continue
        if profile is not None:
            candidates.append((chatbot_id, profile))
    ids = {
        i
        for _, p in candidates
        for i in (
            p.parser_instance_id,
            p.embedding_instance_id,
            p.vector_store_instance_id,
            p.vision_instance_id,
        )
        if i is not None
    }
    providers = {
        r.id: r
        for r in (
            await db.execute(sa.select(ProviderInstance).where(ProviderInstance.id.in_(ids)))
        ).scalars()
    }
    profiles: dict[str, IndexProfile] = {}
    reasons: list[str] = []
    for chatbot_id, profile in candidates:
        rule = rules.get(chatbot_id)
        used = tuple(
            i
            for i in (
                profile.parser_instance_id,
                profile.embedding_instance_id,
                profile.vector_store_instance_id,
                profile.vision_instance_id,
            )
            if i is not None
        )
        if all(may_send(rule, providers.get(i)) for i in used):
            profiles.setdefault(profile.key, profile)
            continue
        log.info("profile.skipped_egress", chatbot_id=str(chatbot_id), profile=profile.key)
        blocked = [
            _blocked(rule, row)
            for i in used
            if (row := providers.get(i)) is not None and not may_send(rule, row)
        ]
        reasons += [f"{names[chatbot_id]}: {b}" for b in blocked or ["a provider is missing"]]
    if profiles:
        return list(profiles.values()), None
    if not candidates:
        return [], (
            f"the pipeline of {', '.join(sorted(names.values()))} has no embedding model or "
            "vector store yet, or no document parser is chosen (on the source, or in the "
            "pipeline when the source has no reading setting)"
        )
    return [], "; ".join(dict.fromkeys(reasons))
