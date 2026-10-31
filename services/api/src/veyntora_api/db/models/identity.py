from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from veyntora_api.db.base import Base, IdMixin, TimestampMixin, VersionedMixin, str_enum, utcnow_col


class GroupSource(StrEnum):
    KEYCLOAK = "keycloak"
    RULE = "rule"
    MANUAL = "manual"


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    keycloak_sub: Mapped[str] = mapped_column(sa.String(255), unique=True)
    email: Mapped[str | None] = mapped_column(sa.String(320), index=True)
    display_name: Mapped[str] = mapped_column(sa.String(255), default="")
    locale: Mapped[str | None] = mapped_column(sa.String(16))
    attributes: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    # Settings page choices (answer language and length, default assistant).
    preferences: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    # A service identity (API app key): no Keycloak account; given groups and roles like a
    # person, never signs in.
    is_service: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
    suspended: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
    suspended_reason: Mapped[str | None] = mapped_column(sa.Text)
    last_login_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # While away: this person may decide the approvals the user could decide, until then.
    approval_delegate_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    approval_delegate_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Group(IdMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(sa.String(255))
    # Keycloak full path (e.g. /support/leads); null for rule-based and manual groups.
    keycloak_path: Mapped[str | None] = mapped_column(sa.String(1024), unique=True)
    keycloak_id: Mapped[str | None] = mapped_column(sa.String(64), unique=True)
    source: Mapped[GroupSource] = mapped_column(str_enum(GroupSource, "group_source"))
    description: Mapped[str] = mapped_column(sa.Text, default="", server_default="")
    # Rule for rule-based groups, e.g. {"all": [{"attr": "department", "eq": "Finance"}]}.
    rule: Mapped[dict[str, Any] | None] = mapped_column()
    owner_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    cost_centre: Mapped[str | None] = mapped_column(sa.String(64))


class Membership(Base):
    __tablename__ = "memberships"

    user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    source: Mapped[GroupSource] = mapped_column(str_enum(GroupSource, "membership_source"))
    created_at: Mapped[datetime] = utcnow_col(nullable=False)
    # Manual memberships may end (pilots, contractors); removed by the hourly job.
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
