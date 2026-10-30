from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import (
    Base,
    IdMixin,
    SecretMetaMixin,
    TimestampMixin,
    VersionedMixin,
    str_enum,
    utcnow_col,
)


class SourceType(StrEnum):
    SHAREPOINT = "sharepoint"
    CONFLUENCE = "confluence"
    SMB = "smb"
    S3 = "s3"
    WEBSITE = "website"
    DATABASE = "database"
    UPLOAD = "upload"


class SourceStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"
    DELETED = "deleted"


class IngestJobKind(StrEnum):
    SYNC = "sync"
    REINDEX = "reindex"
    OCR_RETRY = "ocr_retry"
    ACL_SYNC = "acl_sync"
    UPLOAD = "upload"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IssueKind(StrEnum):
    STALE = "stale"
    CONFLICT = "conflict"
    GAP = "gap"
    PARSE_FAILURE = "parse_failure"


class IssueStatus(StrEnum):
    OPEN = "open"
    NOTIFIED = "notified"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class DataSource(IdMixin, TimestampMixin, VersionedMixin, SecretMetaMixin, Base):
    __tablename__ = "data_sources"

    type: Mapped[SourceType] = mapped_column(str_enum(SourceType, "source_type"))
    name: Mapped[str] = mapped_column(sa.String(255), unique=True)
    config: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    # Cron expression; null means manual sync only.
    schedule: Mapped[str | None] = mapped_column(sa.String(64))
    status: Mapped[SourceStatus] = mapped_column(str_enum(SourceStatus, "source_status"))
    owner_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    # Uploads belong to one user; their chunks are only visible to that user.
    uploaded_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    last_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_acl_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class SourceAttachment(IdMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "source_attachments"
    __table_args__ = (
        sa.UniqueConstraint("chatbot_id", "source_id"),
        sa.CheckConstraint("weight > 0 AND weight <= 10", name="weight_range"),
    )

    chatbot_id: Mapped[UUID] = mapped_column(sa.ForeignKey("chatbots.id", ondelete="CASCADE"))
    source_id: Mapped[UUID] = mapped_column(sa.ForeignKey("data_sources.id", ondelete="CASCADE"))
    # Path prefixes / filters inside the source, e.g. {"include": ["/Policies"], "exclude": []}.
    scope: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    weight: Mapped[float] = mapped_column(sa.Float, default=1.0, server_default="1.0")
    enabled: Mapped[bool] = mapped_column(server_default=sa.true(), default=True)


class Document(IdMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (sa.UniqueConstraint("source_id", "path"),)

    source_id: Mapped[UUID] = mapped_column(sa.ForeignKey("data_sources.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(sa.String(2048))
    title: Mapped[str] = mapped_column(sa.String(1024), default="", server_default="")
    url: Mapped[str | None] = mapped_column(sa.String(2048))
    mime_type: Mapped[str | None] = mapped_column(sa.String(255))
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger)
    language: Mapped[str | None] = mapped_column(sa.String(16))
    hash: Mapped[str | None] = mapped_column(sa.String(128))
    object_key: Mapped[str | None] = mapped_column(sa.String(1024))
    # {"users": [...], "groups": [...]} as synced from the source system.
    acl: Mapped[dict[str, Any]] = mapped_column(server_default='{"users": [], "groups": []}')
    status: Mapped[DocumentStatus] = mapped_column(str_enum(DocumentStatus, "document_status"))
    error: Mapped[str | None] = mapped_column(sa.Text)
    chunk_count: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    source_updated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class IngestJob(IdMixin, Base):
    __tablename__ = "ingest_jobs"

    source_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("data_sources.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE")
    )
    kind: Mapped[IngestJobKind] = mapped_column(str_enum(IngestJobKind, "ingest_job_kind"))
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus, "ingest_job_status"))
    stats: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    error: Mapped[str | None] = mapped_column(sa.Text)
    triggered_by: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class KnowledgeIssue(IdMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_issues"

    kind: Mapped[IssueKind] = mapped_column(str_enum(IssueKind, "knowledge_issue_kind"))
    chatbot_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("chatbots.id", ondelete="CASCADE")
    )
    document_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(sa.Uuid), server_default="{}", default=list
    )
    summary: Mapped[str] = mapped_column(sa.Text)
    details: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    owner_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[IssueStatus] = mapped_column(str_enum(IssueStatus, "knowledge_issue_status"))
    notified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
