from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, list[Any]: JSONB}


def str_enum[E: StrEnum](enum: type[E], name: str) -> sa.Enum:
    """VARCHAR + CHECK instead of a native PG enum, so adding a value is a simple migration."""
    return sa.Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


def utcnow_col(**kw: Any) -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), **kw)


class IdMixin:
    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=sa.text("gen_random_uuid()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    updated_at: Mapped[datetime] = utcnow_col(nullable=False, onupdate=sa.func.now())


class VersionedMixin:
    """Config rows carry an optimistic-concurrency version, bumped by ConfigService."""

    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="1", default=1)


class SecretMetaMixin:
    """Secrets live in OpenBao. Only the reference, last 4 chars and expiry are stored here."""

    secret_ref: Mapped[str | None] = mapped_column(sa.String(512))
    secret_last4: Mapped[str | None] = mapped_column(sa.String(4))
    secret_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
