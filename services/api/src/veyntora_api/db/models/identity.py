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
    suspended: Mapped[bool] = mapped_column(server_default=sa.false(), default=False)
    suspended_reason: Mapped[str | None] = mapped_column(sa.Text)
    last_login_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


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


class AccessReviewStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class AccessReviewItemStatus(StrEnum):
    WAITING = "waiting"
    CONFIRMED = "confirmed"
    OVERDUE = "overdue"


class AccessReview(IdMixin, TimestampMixin, Base):
    __tablename__ = "access_reviews"

    name: Mapped[str] = mapped_column(sa.String(255))
    starts_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    status: Mapped[AccessReviewStatus] = mapped_column(
        str_enum(AccessReviewStatus, "access_review_status")
    )
    created_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))


class AccessReviewItem(IdMixin, Base):
    __tablename__ = "access_review_items"
    __table_args__ = (sa.UniqueConstraint("review_id", "group_id"),)

    review_id: Mapped[UUID] = mapped_column(sa.ForeignKey("access_reviews.id", ondelete="CASCADE"))
    group_id: Mapped[UUID] = mapped_column(sa.ForeignKey("groups.id", ondelete="CASCADE"))
    owner_id: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[AccessReviewItemStatus] = mapped_column(
        str_enum(AccessReviewItemStatus, "access_review_item_status")
    )
    changes: Mapped[dict[str, Any]] = mapped_column(server_default="{}", default=dict)
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decided_by: Mapped[UUID | None] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
