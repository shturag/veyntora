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
    DELETE = "delete"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanStatus(StrEnum):
    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    # Scanning was switched off by configuration (VEY_SCAN_REQUIRED=false); shown in the UI.
    SKIPPED = "skipped"
    # Only for documents read from systems that scan on their side (e.g. SharePoint).
    NOT_REQUIRED = "not_required"


class IndexStatus(StrEnum):
    INDEXED = "indexed"
    FAILED = "failed"


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
    __table_args__ = (
        sa.UniqueConstraint("source_id", "path"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_documents_source_id_external_id"),
    )

    source_id: Mapped[UUID] = mapped_column(sa.ForeignKey("data_sources.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(sa.String(2048))
    # The source system's id (SharePoint drive/item); paths change on rename, this does not.
    external_id: Mapped[str | None] = mapped_column(sa.String(512))
    # The source's version tag (SharePoint cTag); unchanged means no download on sync.
    external_version: Mapped[str | None] = mapped_column(sa.String(255))
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
    scan_status: Mapped[ScanStatus] = mapped_column(
        str_enum(ScanStatus, "document_scan_status"),
        default=ScanStatus.PENDING,
        server_default=ScanStatus.PENDING.value,
    )
    scan_detail: Mapped[str | None] = mapped_column(sa.String(512))
    scanned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    uploaded_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    source_updated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class DocumentIndex(Base):
    """One row per document and index profile (parser + embedding + store + chunking).

    Chatbots whose pipelines share a profile share the chunks. The worker reconciles the
    profiles that attached chatbots need against these rows.
    """

    __tablename__ = "document_indexes"

    document_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    profile_key: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    profile: Mapped[dict[str, Any]] = mapped_column()
    collection: Mapped[str] = mapped_column(sa.String(128))
    vector_store_instance_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("provider_instances.id", ondelete="SET NULL")
    )
    status: Mapped[IndexStatus] = mapped_column(str_enum(IndexStatus, "document_index_status"))
    content_hash: Mapped[str | None] = mapped_column(sa.String(128))
    chunk_count: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(sa.Text)
    indexed_at: Mapped[datetime] = utcnow_col(nullable=False)
    # The document's distinct words under this profile, so re-indexing or removing it can
    # update the vocabulary counts (knowledge.vocabulary).
    terms: Mapped[list[Any]] = mapped_column(server_default="[]", default=list)


class IndexTerm(Base):
    """In how many documents of an index profile a word occurs (compound splitting)."""

    __tablename__ = "index_terms"
    __table_args__ = (
        sa.Index(
            "ix_index_terms_reversed",
            "profile_key",
            "reversed",
            postgresql_ops={"reversed": "text_pattern_ops"},
        ),
    )

    profile_key: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    term: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    # The term spelled backwards: "compounds ending in X" is then a prefix lookup.
    reversed: Mapped[str] = mapped_column(sa.String(128))
    docs: Mapped[int] = mapped_column(sa.Integer, default=1, server_default="1")


class IngestJob(IdMixin, Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (
        # Workers claim queued jobs oldest first.
        sa.Index(
            "ix_ingest_jobs_queued", "created_at", postgresql_where=sa.text("status = 'queued'")
        ),
    )

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
    attempts: Mapped[int] = mapped_column(sa.SmallInteger, default=0, server_default="0")
    # Retries wait until this time (backoff when a dependency such as the scanner is down).
    run_after: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
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
