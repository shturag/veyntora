"""Which index profiles a source must be indexed into.

A source is indexed for every chatbot it is attached to (enabled attachments, chatbot not
archived), for the chatbot's live, canary and current draft pipeline versions, so that a
draft can be tested before it is published.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_spec.pipeline import PipelineSpec
from veyntora_spec.profile import IndexProfile, index_profile

from veyntora_api.db.models.chatbots import (
    Chatbot,
    ChatbotStatus,
    PipelineStatus,
    PipelineVersion,
)
from veyntora_api.db.models.knowledge import SourceAttachment


async def profiles_for_source(db: AsyncSession, source_id: UUID) -> list[IndexProfile]:
    bots = (
        (
            await db.execute(
                sa.select(Chatbot)
                .join(SourceAttachment, SourceAttachment.chatbot_id == Chatbot.id)
                .where(
                    SourceAttachment.source_id == source_id,
                    SourceAttachment.enabled.is_(True),
                    Chatbot.status != ChatbotStatus.ARCHIVED,
                )
            )
        )
        .scalars()
        .all()
    )
    if not bots:
        return []
    version_ids = {v for b in bots for v in (b.live_version_id, b.canary_version_id) if v}
    drafts = sa.select(PipelineVersion.id).where(
        PipelineVersion.chatbot_id.in_([b.id for b in bots]),
        PipelineVersion.status == PipelineStatus.DRAFT,
    )
    version_ids |= set((await db.execute(drafts)).scalars())
    specs = (
        await db.execute(sa.select(PipelineVersion.spec).where(PipelineVersion.id.in_(version_ids)))
    ).scalars()
    profiles: dict[str, IndexProfile] = {}
    for raw in specs:
        try:
            profile = index_profile(PipelineSpec.model_validate(raw))
        except ValidationError:
            continue
        if profile is not None:
            profiles.setdefault(profile.key, profile)
    return list(profiles.values())
