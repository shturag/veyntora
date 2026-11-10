"""How each data source reads its documents and which of its files it reads (ADR 0040).

Stored in the source's config under "reading". A source without an extraction setting is read
as the pipeline of each chatbot it is attached to says, as before ADR 0040.
"""

from __future__ import annotations

import fnmatch
import posixpath
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import Capability
from veyntora_spec.extraction import ExtractionMethod, ExtractionSpec, FileFilters, SourceReading

from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.knowledge import DataSource, IngestJobKind
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.knowledge.service import UPLOAD_TYPES, KnowledgeError, enqueue


def reading_of(source: DataSource) -> SourceReading:
    raw = (source.config or {}).get("reading")
    return SourceReading.model_validate(raw) if raw else SourceReading()


def extraction_of(source: DataSource) -> ExtractionSpec | None:
    return reading_of(source).extraction


def skipped(filters: FileFilters, path: str, size: int | None, limit: int) -> str | None:
    """Why a file is not read ("filtered", "too_large"), or None to read it."""
    name = posixpath.basename(path.rstrip("/")) or path
    ext = posixpath.splitext(name)[1].lower().lstrip(".")
    if filters.file_types and ext not in filters.file_types:
        return "filtered"
    if filters.include and not any(_matches(path, p) for p in filters.include):
        return "filtered"
    if any(_matches(path, p) for p in filters.exclude):
        return "filtered"
    cap = min(limit, filters.max_file_mb * 1024 * 1024) if filters.max_file_mb else limit
    if size is not None and size > cap:
        return "too_large"
    return None


def size_limit(filters: FileFilters, limit: int) -> int:
    return min(limit, filters.max_file_mb * 1024 * 1024) if filters.max_file_mb else limit


def _matches(path: str, pattern: str) -> bool:
    """A glob on the whole path ("/policies/*") or, without a slash, on the name ("*.pdf")."""
    pattern = pattern.strip()
    if "/" not in pattern:
        return fnmatch.fnmatch(posixpath.basename(path).lower(), pattern.lower())
    full = "/" + path.lstrip("/")
    return fnmatch.fnmatch(full.lower(), ("/" + pattern.lstrip("/")).lower())


async def check_reading(db: AsyncSession, reading: SourceReading) -> None:
    unknown = [t for t in reading.filters.file_types if f".{t}" not in UPLOAD_TYPES]
    if unknown:
        raise KnowledgeError(f"these file types cannot be read: {', '.join(unknown)}")
    ex = reading.extraction
    if ex is None:
        return
    wanted = {ex.parser_instance_id: Capability.PARSER, ex.vision_instance_id: Capability.VISION}
    ids = [i for i in wanted if i is not None]
    found = {
        p.id: p
        for p in (
            await db.execute(sa.select(ProviderInstance).where(ProviderInstance.id.in_(ids)))
        ).scalars()
    }
    if ex.parser_instance_id is None:
        raise KnowledgeError("choose the document parser")
    for instance_id, capability in wanted.items():
        if instance_id is None:
            continue
        row = found.get(instance_id)
        if row is None or row.capability is not capability:
            raise KnowledgeError(f"choose a {capability.value} provider for this setting")
    if ex.method is ExtractionMethod.VISION and ex.vision_instance_id is None:
        raise KnowledgeError("reading pages with a vision model needs a vision model")


async def set_reading(
    db: AsyncSession,
    ctx: RequestContext,
    source: DataSource,
    reading: SourceReading,
    *,
    expected_version: int | None,
    triggered_by: UUID | None,
) -> DataSource:
    """Save how the source reads its documents. A new reading indexes the documents again
    (they get a new index profile); new filters take effect with the next sync."""
    await check_reading(db, reading)
    before = reading_of(source)
    config = {**source.config, "reading": reading.model_dump(mode="json", exclude_none=True)}
    if before.filters != reading.filters:
        # Change feeds (SharePoint Online) report only changes: start over, so files the new
        # filters exclude or let in are seen.
        config["state"] = {**(config.get("state") or {}), "delta": {}}
    await ConfigService(db, ctx).update(
        source, {"config": config}, expected_version=expected_version, action="source.reading"
    )
    if before != reading:
        await enqueue(db, source.id, IngestJobKind.SYNC, triggered_by=triggered_by)
    return source
