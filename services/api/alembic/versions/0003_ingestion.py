"""ingestion bookkeeping: scan status, uploader, per-profile document indexes, job attempts

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_KINDS_OLD = ("sync", "reindex", "ocr_retry", "acl_sync", "upload")
_JOB_KINDS_NEW = (*_JOB_KINDS_OLD, "delete")


def _kind_check(kinds: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_ingest_jobs_ingest_job_kind"), "ingest_jobs", type_="check")
    values = ", ".join(f"'{k}'" for k in kinds)
    op.create_check_constraint(
        op.f("ck_ingest_jobs_ingest_job_kind"), "ingest_jobs", f"kind IN ({values})"
    )


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "scan_status",
            sa.Enum(
                "pending",
                "clean",
                "infected",
                "skipped",
                "not_required",
                name="document_scan_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column("documents", sa.Column("scan_detail", sa.String(length=512), nullable=True))
    op.add_column("documents", sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("uploaded_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_uploaded_by_users"),
        "documents",
        "users",
        ["uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "document_indexes",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("profile_key", sa.String(length=32), nullable=False),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("collection", sa.String(length=128), nullable=False),
        sa.Column("vector_store_instance_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "indexed",
                "failed",
                name="document_index_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_indexes_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vector_store_instance_id"],
            ["provider_instances.id"],
            name=op.f("fk_document_indexes_vector_store_instance_id_provider_instances"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("document_id", "profile_key", name=op.f("pk_document_indexes")),
    )

    op.add_column(
        "ingest_jobs", sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False)
    )
    op.add_column(
        "ingest_jobs", sa.Column("run_after", sa.DateTime(timezone=True), nullable=True)
    )
    _kind_check(_JOB_KINDS_NEW)
    # The worker claims queued jobs oldest first.
    op.create_index(
        "ix_ingest_jobs_queued",
        "ingest_jobs",
        ["created_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index("ix_ingest_jobs_queued", table_name="ingest_jobs")
    op.execute("DELETE FROM ingest_jobs WHERE kind = 'delete'")
    _kind_check(_JOB_KINDS_OLD)
    op.drop_column("ingest_jobs", "run_after")
    op.drop_column("ingest_jobs", "attempts")
    op.drop_table("document_indexes")
    op.drop_constraint(op.f("fk_documents_uploaded_by_users"), "documents", type_="foreignkey")
    op.drop_column("documents", "uploaded_by")
    op.drop_column("documents", "scanned_at")
    op.drop_column("documents", "scan_detail")
    op.drop_column("documents", "scan_status")
