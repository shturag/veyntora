"""S3 buckets and websites as connected sources (Phase 6).

Neither system has permissions Veyntora can map person by person, so who may read is set
here: the source's readers, and optionally readers per folder (S3 prefix or website
path). A folder rule replaces the source's readers below that folder; the longest
matching folder wins. Changing either re-applies permissions to every document.

The S3 secret access key goes to OpenBao (write-only, like every secret); the access key
id is not secret. Websites are read without credentials; only hosts of the start pages
are followed and robots.txt is respected.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.identity import Group
from veyntora_api.db.models.knowledge import DataSource, IngestJobKind, SourceStatus, SourceType
from veyntora_api.knowledge.service import (
    SCHEDULES,
    KnowledgeError,
    SourceAcl,
    _check_acl,
    enqueue,
    set_source_secret,
)
from veyntora_api.secrets.openbao import SecretWriter

CONNECTED = (SourceType.S3, SourceType.WEBSITE)
_URL = r"^https?://[^/\s]+(/\S*)?$"


class S3Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Empty: AWS. On-premises stores (MinIO, SeaweedFS, Ceph) give their URL.
    endpoint_url: str | None = Field(None, max_length=1024, pattern=_URL)
    region: str = Field("us-east-1", min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    bucket: str = Field(min_length=3, max_length=63, pattern=r"^[a-z0-9][a-z0-9.-]+[a-z0-9]$")
    # Key prefixes to read ("policies/hr/"); empty means the whole bucket.
    prefixes: list[str] = Field(default_factory=list, max_length=50)
    access_key_id: str = Field(min_length=3, max_length=128)


class WebsiteSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_urls: list[str] = Field(min_length=1, max_length=20)
    # Only pages below these paths are read ("/handbook/"); empty means the whole site.
    include_paths: list[str] = Field(default_factory=list, max_length=50)
    max_pages: int = Field(500, ge=1, le=5000)
    max_depth: int = Field(3, ge=0, le=10)

    @model_validator(mode="after")
    def _urls(self) -> WebsiteSettings:
        for url in self.start_urls:
            if len(url) > 2048 or not re.match(_URL, url):
                raise ValueError(f"{url!r} is not an http(s) address")
        return self


class FolderReaders(BaseModel):
    """Readers for one folder (S3 prefix or website path)."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    groups: list[UUID] = Field(min_length=1, max_length=50)


class ConnectedSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    type: Literal["s3", "website"]
    s3: S3Settings | None = None
    website: WebsiteSettings | None = None
    acl: SourceAcl
    folders: list[FolderReaders] = Field(default_factory=list, max_length=100)
    # S3 only: the secret access key.
    secret: SecretStr | None = None
    secret_expires_at: datetime | None = None
    schedule: str | None = None

    @model_validator(mode="after")
    def _matches(self) -> ConnectedSourceInput:
        if self.type == "s3" and (self.s3 is None or self.website is not None):
            raise ValueError("an S3 source needs s3 settings")
        if self.type == "website" and (self.website is None or self.s3 is not None):
            raise ValueError("a website source needs website settings")
        if self.type == "s3" and self.secret is None:
            raise ValueError("an S3 source needs the secret access key")
        return self


def _norm(path: str) -> str:
    return "/" + path.strip().strip("/")


def readers_for(source: DataSource, path: str) -> dict[str, list[str]]:
    """The ACL for a document at `path` (S3 key or URL path): the longest matching folder
    rule, else the source's readers."""
    target = _norm(path) + "/"
    best: dict[str, Any] | None = None
    for rule in source.config.get("folders") or []:
        prefix = _norm(str(rule["path"])).rstrip("/") + "/"
        if target.startswith(prefix) and (
            best is None or len(prefix) > len(_norm(str(best["path"])))
        ):
            best = rule
    if best is not None:
        return {"users": [], "groups": sorted(str(g) for g in best["groups"])}
    acl = SourceAcl.model_validate(source.config.get("acl") or {})
    return {
        "users": sorted(str(u) for u in acl.users),
        "groups": sorted(str(g) for g in acl.groups),
    }


async def _check_folders(db: AsyncSession, folders: list[FolderReaders]) -> None:
    ids = {g for f in folders for g in f.groups}
    if ids:
        found = set((await db.execute(sa.select(Group.id).where(Group.id.in_(ids)))).scalars())
        if missing := [str(g) for g in ids if g not in found]:
            raise KnowledgeError(f"unknown groups: {', '.join(missing)}")


def settings_of(source: DataSource) -> S3Settings | WebsiteSettings:
    model: type[S3Settings | WebsiteSettings] = (
        S3Settings if source.type is SourceType.S3 else WebsiteSettings
    )
    return model.model_validate({k: source.config.get(k) for k in model.model_fields})


async def create_connected_source(
    db: AsyncSession,
    ctx: RequestContext,
    secrets: SecretWriter | None,
    data: ConnectedSourceInput,
    owner_id: UUID | None,
) -> DataSource:
    if data.schedule not in (None, *SCHEDULES):
        raise KnowledgeError("choose one of the offered sync schedules")
    await _check_acl(db, data.acl)
    await _check_folders(db, data.folders)
    if await db.scalar(sa.select(DataSource.id).where(DataSource.name == data.name)):
        raise KnowledgeError(f"a source named {data.name!r} already exists")
    settings = data.s3 if data.type == "s3" else data.website
    if settings is None:  # the input model checks this too
        raise KnowledgeError(f"{data.type} settings are missing")
    row = DataSource(
        type=SourceType(data.type),
        name=data.name,
        config={
            **settings.model_dump(mode="json"),
            "acl": data.acl.model_dump(mode="json"),
            "folders": [f.model_dump(mode="json") for f in data.folders],
            "state": {},
        },
        schedule=data.schedule,
        status=SourceStatus.ACTIVE,
        owner_id=owner_id,
    )
    await ConfigService(db, ctx).create(row, action="source.create")
    if data.secret is not None:
        await set_source_secret(
            db, ctx, secrets, row, value=data.secret, expires_at=data.secret_expires_at
        )
    await enqueue(db, row.id, IngestJobKind.SYNC)
    return row


class ConnectedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    s3: S3Settings | None = None
    website: WebsiteSettings | None = None
    folders: list[FolderReaders] | None = Field(None, max_length=100)


async def update_connected(
    db: AsyncSession,
    ctx: RequestContext,
    row: DataSource,
    data: ConnectedUpdate,
    *,
    expected_version: int | None,
    triggered_by: UUID | None,
) -> DataSource:
    if row.type not in CONNECTED:
        raise KnowledgeError("these settings only apply to S3 and website sources")
    settings = data.s3 if row.type is SourceType.S3 else data.website
    if (data.s3 if row.type is SourceType.WEBSITE else data.website) is not None:
        raise KnowledgeError("these settings are for another kind of source")
    config = dict(row.config)
    resync = acl_changed = False
    if settings is not None:
        config.update(settings.model_dump(mode="json"))
        resync = True
    if data.folders is not None:
        await _check_folders(db, data.folders)
        new = [f.model_dump(mode="json") for f in data.folders]
        acl_changed = new != (row.config.get("folders") or [])
        config["folders"] = new
    await ConfigService(db, ctx).update(
        row, {"config": config}, expected_version=expected_version, action="source.update"
    )
    if acl_changed:
        await enqueue(db, row.id, IngestJobKind.ACL_SYNC, triggered_by=triggered_by)
    if resync:
        await enqueue(db, row.id, IngestJobKind.SYNC, triggered_by=triggered_by)
    return row
