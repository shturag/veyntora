"""Connected sources read as a listing: the reader for a source, for syncs and tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from veyntora_api.db.models.knowledge import DataSource
from veyntora_api.knowledge.connectors import (
    CmisSettings,
    ConfluenceSettings,
    DatabaseSettings,
    GitSettings,
    JiraSettings,
    S3Settings,
    ServiceNowSettings,
    SharePointServerSettings,
    SmbSettings,
    WebdavSettings,
    WebsiteSettings,
    settings_of,
)
from veyntora_api.knowledge.service import KnowledgeError

from veyntora_workers.connectors.cmis import CmisReader
from veyntora_workers.connectors.confluence import ConfluenceReader
from veyntora_workers.connectors.database import DatabaseReader
from veyntora_workers.connectors.git import GitReader
from veyntora_workers.connectors.jira import JiraReader
from veyntora_workers.connectors.s3 import S3Reader
from veyntora_workers.connectors.servicenow import ServiceNowReader
from veyntora_workers.connectors.sharepoint_server import SharePointServerReader
from veyntora_workers.connectors.smb import SmbReader
from veyntora_workers.connectors.webdav import WebdavReader
from veyntora_workers.connectors.website import WebsiteReader

if TYPE_CHECKING:
    from veyntora_workers.ingest import Ingestor

Reader = (
    S3Reader
    | WebsiteReader
    | ConfluenceReader
    | DatabaseReader
    | SmbReader
    | WebdavReader
    | SharePointServerReader
    | CmisReader
    | GitReader
    | ServiceNowReader
    | JiraReader
)


async def _secret(ing: Ingestor, source: DataSource) -> str:
    if not source.secret_ref:
        raise KnowledgeError("the secret (key, token or password) is not set")
    return await ing.secrets.read(source.secret_ref)


async def reader_for(ing: Ingestor, source: DataSource) -> Reader:
    cfg = settings_of(source)
    if isinstance(cfg, WebsiteSettings):
        return WebsiteReader(
            cfg,
            max_bytes=ing.settings.upload_max_bytes,
            secret=await _secret(ing, source) if cfg.auth != "none" else None,
            browser_url=ing.settings.browser_url,
        )
    secret = await _secret(ing, source)
    reader: Reader
    match cfg:
        case S3Settings():
            reader = S3Reader(cfg, secret)
        case ConfluenceSettings():
            reader = ConfluenceReader(cfg, secret, ing.db)
        case DatabaseSettings():
            reader = DatabaseReader(cfg, secret, ing.db)
        case SmbSettings():
            reader = SmbReader(cfg, secret, max_bytes=ing.settings.upload_max_bytes)
        case WebdavSettings():
            reader = WebdavReader(cfg, secret)
        case SharePointServerSettings():
            reader = SharePointServerReader(cfg, secret, ing.db)
        case CmisSettings():
            reader = CmisReader(cfg, secret, ing.db)
        case GitSettings():
            reader = GitReader(cfg, secret)
        case ServiceNowSettings():
            reader = ServiceNowReader(cfg, secret)
        case JiraSettings():
            reader = JiraReader(cfg, secret)
        case _:
            raise KnowledgeError(f"{source.type.value} sources are not read this way")
    return reader


async def close(reader: Reader) -> None:
    if not isinstance(reader, S3Reader | DatabaseReader):
        await reader.close()
