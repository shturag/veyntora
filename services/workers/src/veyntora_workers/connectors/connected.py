"""S3 and website sources: the reader for a source, for syncs and connection tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from veyntora_api.db.models.knowledge import DataSource, SourceType
from veyntora_api.knowledge.connectors import S3Settings, WebsiteSettings, settings_of
from veyntora_api.knowledge.service import KnowledgeError

from veyntora_workers.connectors.s3 import S3Reader
from veyntora_workers.connectors.website import WebsiteReader

if TYPE_CHECKING:
    from veyntora_workers.ingest import Ingestor


async def reader_for(ing: Ingestor, source: DataSource) -> S3Reader | WebsiteReader:
    cfg = settings_of(source)
    if source.type is SourceType.S3 and isinstance(cfg, S3Settings):
        if not source.secret_ref:
            raise KnowledgeError("the secret access key is not set")
        return S3Reader(cfg, await ing.secrets.read(source.secret_ref))
    if source.type is SourceType.WEBSITE and isinstance(cfg, WebsiteSettings):
        return WebsiteReader(cfg, max_bytes=ing.settings.upload_max_bytes)
    raise KnowledgeError(f"{source.type.value} sources are not read this way")


async def close(reader: S3Reader | WebsiteReader) -> None:
    if isinstance(reader, WebsiteReader):
        await reader.close()
