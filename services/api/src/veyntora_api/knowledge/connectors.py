"""Connected sources read as a listing: S3 buckets and websites (Phase 6), Confluence,
databases and file shares (Phase 7); Nextcloud/WebDAV, SharePoint Server, document
management systems (CMIS), Git repositories, ServiceNow knowledge and Jira (ADR 0036).

- S3 and websites have no permissions Veyntora can map person by person, so who may read
  is set here: the source's readers, and optionally readers per folder (S3 prefix or
  website path). A folder rule replaces the source's readers below that folder; the
  longest matching folder wins.
- Confluence, file shares, SharePoint Server and CMIS bring their own permissions (space
  permissions and page restrictions; NTFS ACLs; role assignments; CMIS ACLs). They are
  mapped to Veyntora through the source's group map; anything that cannot be mapped is
  dropped (fail closed) and listed on the source.
- Nextcloud/WebDAV, Git, ServiceNow and Jira use the source's readers and folder rules
  (folder: a WebDAV folder, "repository/path", "knowledge base/…", "PROJECT/…").
  ServiceNow articles with their own read criteria and Jira issues with a security level
  are skipped unless the admin includes them: Veyntora cannot evaluate those rules.
- Databases: a read-only query; each row becomes a document. Readers are the source's,
  or per row from a column naming a Veyntora group.

Every secret (S3 key, Confluence token, database and share passwords) goes to OpenBao,
write-only. Changing readers or maps re-applies permissions to every document.
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

CONNECTED = (
    SourceType.S3,
    SourceType.WEBSITE,
    SourceType.CONFLUENCE,
    SourceType.DATABASE,
    SourceType.SMB,
    SourceType.WEBDAV,
    SourceType.SHAREPOINT_SERVER,
    SourceType.CMIS,
    SourceType.GIT,
    SourceType.SERVICENOW,
    SourceType.JIRA,
)
# Their permissions come from the source system (mapped), not from Veyntora's readers.
OWN_PERMISSIONS = (
    SourceType.CONFLUENCE,
    SourceType.SMB,
    SourceType.SHAREPOINT_SERVER,
    SourceType.CMIS,
)
KINDS = tuple(t.value for t in CONNECTED)
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


class ConfluenceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flavour: Literal["cloud", "datacenter"] = "cloud"
    # Cloud: https://example.atlassian.net/wiki · Data Center: https://confluence.example.com
    base_url: str = Field(max_length=1024, pattern=_URL)
    # Cloud: the account's e-mail (with an API token); Data Center: empty (personal token).
    email: str | None = Field(None, max_length=320)
    spaces: list[str] = Field(min_length=1, max_length=50)
    # Confluence group name -> Veyntora group.
    group_map: dict[str, UUID] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _cloud_email(self) -> ConfluenceSettings:
        if self.flavour == "cloud" and not self.email:
            raise ValueError(
                "Confluence Cloud needs the e-mail of the account the token belongs to"
            )
        return self


Engine = Literal["postgresql", "sqlserver", "mysql", "oracle"]
_SELECT = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_WRITE = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|exec|execute|call)\b",
    re.IGNORECASE,
)


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Engine
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    # One SELECT; each row becomes a document.
    query: str = Field(min_length=8, max_length=8000)
    id_column: str = Field(min_length=1, max_length=128)
    title_column: str = Field(min_length=1, max_length=128)
    # Columns written into the document (empty: all except the id).
    text_columns: list[str] = Field(default_factory=list, max_length=100)
    # Optional: a column whose value names the Veyntora group that may read the row.
    group_column: str | None = Field(None, max_length=128)
    max_rows: int = Field(10_000, ge=1, le=100_000)

    @model_validator(mode="after")
    def _read_only(self) -> DatabaseSettings:
        if (
            not _SELECT.match(self.query)
            or _WRITE.search(self.query)
            or ";" in self.query.strip("; \n")
        ):
            raise ValueError("the query must be one SELECT (or WITH … SELECT) that changes nothing")
        return self


class SmbSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.-]+$")
    port: int = Field(445, ge=1, le=65535)
    share: str = Field(min_length=1, max_length=255)
    # Folders inside the share ("Policies/HR"); empty means the whole share.
    include_paths: list[str] = Field(default_factory=list, max_length=50)
    # DOMAIN\\user or user@domain.
    username: str = Field(min_length=1, max_length=255)
    # Windows SID (groups, or well-known ones such as S-1-1-0 Everyone) -> Veyntora group.
    sid_map: dict[str, UUID] = Field(default_factory=dict)


def _paths(paths: list[str]) -> list[str]:
    return [p.strip().strip("/") for p in paths if p.strip().strip("/")]


class WebdavSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Nextcloud/ownCloud: the server address (files are under /remote.php/dav/files/<user>);
    # generic: the WebDAV address of the folder to read.
    flavour: Literal["nextcloud", "generic"] = "nextcloud"
    base_url: str = Field(max_length=1024, pattern=_URL)
    # The account (Nextcloud: with an app password as the secret).
    username: str = Field(min_length=1, max_length=255)
    # Folders to read ("Shared/Policies"); empty means everything the account sees.
    include_paths: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _clean(self) -> WebdavSettings:
        self.include_paths = _paths(self.include_paths)
        return self


class SharePointServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # SharePoint 2016, 2019 or Subscription Edition: the site's address.
    site_url: str = Field(max_length=1024, pattern=_URL)
    # DOMAIN\user (Windows sign-in, NTLM) or the account for basic sign-in over HTTPS.
    username: str = Field(min_length=1, max_length=255)
    auth: Literal["ntlm", "basic"] = "ntlm"
    # Document libraries by title; empty means every document library of the site.
    libraries: list[str] = Field(default_factory=list, max_length=50)
    # Folders inside the libraries ("Shared Documents/HR"); empty means all.
    include_paths: list[str] = Field(default_factory=list, max_length=50)
    # SharePoint group name, Active Directory group (DOMAIN\group or SID) or claim
    # (c:0(.s|true: all users) -> Veyntora group.
    group_map: dict[str, UUID] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _clean(self) -> SharePointServerSettings:
        self.include_paths = _paths(self.include_paths)
        return self


class CmisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The CMIS 1.1 browser binding address (Alfresco: …/api/-default-/public/cmis/versions/
    # 1.1/browser); d.velop, enaio, OpenText and others publish their own.
    browser_url: str = Field(max_length=1024, pattern=_URL)
    # Empty: the first repository.
    repository_id: str | None = Field(None, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    # Folder paths to read ("/Sites/hr/documentLibrary").
    folders: list[str] = Field(min_length=1, max_length=50)
    # CMIS principal (GROUP_hr, GROUP_EVERYONE, …) -> Veyntora group. Users map by e-mail.
    group_map: dict[str, UUID] = Field(default_factory=dict)
    max_documents: int = Field(10_000, ge=1, le=100_000)


class GitSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["github", "gitlab"] = "github"
    # Empty: github.com or gitlab.com. GitHub Enterprise: https://github.example.com/api/v3;
    # GitLab self-managed: https://gitlab.example.com.
    base_url: str | None = Field(None, max_length=1024, pattern=_URL)
    # "owner/repo" (GitHub) or "group/subgroup/project" (GitLab).
    repositories: list[str] = Field(min_length=1, max_length=20)
    # Empty: each repository's default branch.
    branch: str | None = Field(None, max_length=255)
    # Folders inside each repository ("docs"); empty means the whole repository.
    include_paths: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _clean(self) -> GitSettings:
        for repo in self.repositories:
            if not re.match(r"^[\w.-]+(/[\w.-]+)+$", repo):
                raise ValueError(f"{repo!r} is not owner/repository")
        self.include_paths = _paths(self.include_paths)
        return self


class ServiceNowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_url: str = Field(max_length=1024, pattern=_URL)
    username: str = Field(min_length=1, max_length=255)
    # Knowledge bases by title; empty means every knowledge base the account can read.
    knowledge_bases: list[str] = Field(default_factory=list, max_length=50)
    # Articles with their own "Can read" criteria are skipped (fail closed).
    include_restricted: bool = False
    max_articles: int = Field(10_000, ge=1, le=100_000)


class JiraSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flavour: Literal["cloud", "datacenter"] = "cloud"
    # Cloud: https://example.atlassian.net · Data Center: https://jira.example.com
    base_url: str = Field(max_length=1024, pattern=_URL)
    # Cloud: the account's e-mail (with an API token); Data Center: empty (personal token).
    email: str | None = Field(None, max_length=320)
    projects: list[str] = Field(min_length=1, max_length=50)
    # Added to the project filter with AND; the default keeps solved tickets.
    jql: str = Field("statusCategory = Done", max_length=2000)
    include_comments: bool = True
    # Issues with a security level are skipped (fail closed).
    include_secured: bool = False
    max_issues: int = Field(5000, ge=1, le=50_000)

    @model_validator(mode="after")
    def _check(self) -> JiraSettings:
        if self.flavour == "cloud" and not self.email:
            raise ValueError("Jira Cloud needs the e-mail of the account the token belongs to")
        for key in self.projects:
            if not re.match(r"^[A-Z][A-Z0-9_]{0,49}$", key):
                raise ValueError(f"{key!r} is not a project key (such as HELP)")
        if re.search(r"\border\s+by\b", self.jql, re.IGNORECASE):
            raise ValueError("leave out ORDER BY: Veyntora orders the issues itself")
        return self


class FolderReaders(BaseModel):
    """Readers for one folder (S3 prefix or website path)."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)
    groups: list[UUID] = Field(min_length=1, max_length=50)


class ConnectedSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    type: Literal[
        "s3",
        "website",
        "confluence",
        "database",
        "smb",
        "webdav",
        "sharepoint_server",
        "cmis",
        "git",
        "servicenow",
        "jira",
    ]
    s3: S3Settings | None = None
    website: WebsiteSettings | None = None
    confluence: ConfluenceSettings | None = None
    database: DatabaseSettings | None = None
    smb: SmbSettings | None = None
    webdav: WebdavSettings | None = None
    sharepoint_server: SharePointServerSettings | None = None
    cmis: CmisSettings | None = None
    git: GitSettings | None = None
    servicenow: ServiceNowSettings | None = None
    jira: JiraSettings | None = None
    # Readers for sources without permissions of their own (see OWN_PERMISSIONS).
    acl: SourceAcl = Field(default_factory=SourceAcl)
    folders: list[FolderReaders] = Field(default_factory=list, max_length=100)
    # The key, token or password (every source but websites).
    secret: SecretStr | None = None
    secret_expires_at: datetime | None = None
    schedule: str | None = None

    @model_validator(mode="after")
    def _matches(self) -> ConnectedSourceInput:
        given = [k for k in KINDS if getattr(self, k)]
        if given != [self.type]:
            raise ValueError(f"a {self.type} source needs {self.type} settings (only those)")
        if self.type != "website" and self.secret is None:
            raise ValueError("this source needs its secret (key, token or password)")
        return self

    def settings(self) -> BaseModel:
        value: BaseModel | None = getattr(self, self.type)
        if value is None:
            raise ValueError(f"{self.type} settings are missing")
        return value


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


Connection = (
    S3Settings
    | WebsiteSettings
    | ConfluenceSettings
    | DatabaseSettings
    | SmbSettings
    | WebdavSettings
    | SharePointServerSettings
    | CmisSettings
    | GitSettings
    | ServiceNowSettings
    | JiraSettings
)
MODELS: dict[SourceType, type[Connection]] = {
    SourceType.S3: S3Settings,
    SourceType.WEBSITE: WebsiteSettings,
    SourceType.CONFLUENCE: ConfluenceSettings,
    SourceType.DATABASE: DatabaseSettings,
    SourceType.SMB: SmbSettings,
    SourceType.WEBDAV: WebdavSettings,
    SourceType.SHAREPOINT_SERVER: SharePointServerSettings,
    SourceType.CMIS: CmisSettings,
    SourceType.GIT: GitSettings,
    SourceType.SERVICENOW: ServiceNowSettings,
    SourceType.JIRA: JiraSettings,
}


def settings_of(source: DataSource) -> Connection:
    model = MODELS[source.type]
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
    if SourceType(data.type) not in OWN_PERMISSIONS:
        await _check_acl(db, data.acl)
    await _check_folders(db, data.folders)
    await _check_maps(db, data.settings())
    if await db.scalar(sa.select(DataSource.id).where(DataSource.name == data.name)):
        raise KnowledgeError(f"a source named {data.name!r} already exists")
    settings = data.settings()
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


async def _check_maps(db: AsyncSession, settings: BaseModel) -> None:
    mapping: dict[str, UUID] = dict(
        getattr(settings, "group_map", None) or getattr(settings, "sid_map", None) or {}
    )
    ids = set(mapping.values())
    if ids:
        found = set((await db.execute(sa.select(Group.id).where(Group.id.in_(ids)))).scalars())
        if missing := [str(g) for g in ids if g not in found]:
            raise KnowledgeError(f"unknown groups: {', '.join(missing)}")


class ConnectedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    s3: S3Settings | None = None
    website: WebsiteSettings | None = None
    confluence: ConfluenceSettings | None = None
    database: DatabaseSettings | None = None
    smb: SmbSettings | None = None
    webdav: WebdavSettings | None = None
    sharepoint_server: SharePointServerSettings | None = None
    cmis: CmisSettings | None = None
    git: GitSettings | None = None
    servicenow: ServiceNowSettings | None = None
    jira: JiraSettings | None = None
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
        raise KnowledgeError("these settings only apply to connected sources")
    given = {k for k in KINDS if getattr(data, k)}
    if given - {row.type.value}:
        raise KnowledgeError("these settings are for another kind of source")
    settings: BaseModel | None = getattr(data, row.type.value)
    config = dict(row.config)
    resync = acl_changed = False
    if settings is not None:
        await _check_maps(db, settings)
        new = settings.model_dump(mode="json")
        maps = ("group_map", "sid_map", "group_column")
        acl_changed = any(config.get(k) != new.get(k) for k in maps if k in new)
        config.update(new)
        resync = True
    if data.folders is not None:
        await _check_folders(db, data.folders)
        folders = [f.model_dump(mode="json") for f in data.folders]
        acl_changed = acl_changed or folders != (row.config.get("folders") or [])
        config["folders"] = folders
    await ConfigService(db, ctx).update(
        row, {"config": config}, expected_version=expected_version, action="source.update"
    )
    if acl_changed:
        await enqueue(db, row.id, IngestJobKind.ACL_SYNC, triggered_by=triggered_by)
    if resync:
        await enqueue(db, row.id, IngestJobKind.SYNC, triggered_by=triggered_by)
    return row
