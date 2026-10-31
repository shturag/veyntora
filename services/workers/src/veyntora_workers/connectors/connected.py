"""Connected sources read as a listing: the reader for a source, for syncs and tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from veyntora_api.db.models.knowledge import DataSource
from veyntora_api.knowledge.connectors import (
    ConfluenceSettings,
    DatabaseSettings,
    S3Settings,
    SmbSettings,
    WebsiteSettings,
    settings_of,
)
from veyntora_api.knowledge.service import KnowledgeError

from veyntora_workers.connectors.confluence import ConfluenceReader
from veyntora_workers.connectors.database import DatabaseReader
from veyntora_workers.connectors.s3 import S3Reader
from veyntora_workers.connectors.smb import SmbReader
from veyntora_workers.connectors.website import WebsiteReader

if TYPE_CHECKING:
    from veyntora_workers.ingest import Ingestor

Reader = S3Reader | WebsiteReader | ConfluenceReader | DatabaseReader | SmbReader


async def _secret(ing: Ingestor, source: DataSource) -> str:
    if not source.secret_ref:
        raise KnowledgeError("the secret (key, token or password) is not set")
    return await ing.secrets.read(source.secret_ref)


async def reader_for(ing: Ingestor, source: DataSource) -> Reader:
    cfg = settings_of(source)
    if isinstance(cfg, WebsiteSettings):
        return WebsiteReader(cfg, max_bytes=ing.settings.upload_max_bytes)
    secret = await _secret(ing, source)
    if isinstance(cfg, S3Settings):
        return S3Reader(cfg, secret)
    if isinstance(cfg, ConfluenceSettings):
        return ConfluenceReader(cfg, secret, ing.db)
    if isinstance(cfg, DatabaseSettings):
        return DatabaseReader(cfg, secret, ing.db)
    if isinstance(cfg, SmbSettings):
        return SmbReader(cfg, secret, max_bytes=ing.settings.upload_max_bytes)
    raise KnowledgeError(f"{source.type.value} sources are not read this way")


async def close(reader: Reader) -> None:
    if isinstance(reader, WebsiteReader | ConfluenceReader | SmbReader):
        await reader.close()
