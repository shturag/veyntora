"""Notifications to people and messages from automations (Phase 5).

- `notify_user`: shown in Veyntora (the bell), and sent to the person's Teams chat with a
  chatbot's bot (when they have one and did not turn it off) and by email (when the mail
  relay is set up and they did not turn it off).
- `queue_post`: an automation's notify step: a Teams or Slack channel post, Teams chats
  with people, or emails.

Everything outside Veyntora is queued as a `Delivery` and sent by the channels service
(Teams, Slack: the chatbot's own bot) or the workers (email), so a slow or failing
platform never holds up a run, and the run shows what was sent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core import audit
from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.channels import ChannelDestination, DestinationKind
from veyntora_api.db.models.identity import User
from veyntora_api.db.models.notifications import Delivery, DeliveryStatus, Notification
from veyntora_api.db.models.platform import PlatformSettings
from veyntora_api.secrets.openbao import SecretWriter

SMTP_PATH = "platform/smtp"
MAX_TEXT = 8000


class NotifyError(ValueError):
    pass


# ---------------------------------------------------------------- mail relay


class MailSettings(BaseModel):
    """The SMTP relay emails are sent through. The password is set separately."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.-]+$")
    port: int = Field(587, ge=1, le=65535)
    # starttls (587), tls (465) or none (only for a relay inside the network).
    security: str = Field("starttls", pattern=r"^(starttls|tls|none)$")
    username: str | None = Field(default=None, max_length=255)
    from_address: EmailStr
    from_name: str = Field("Veyntora", max_length=255)


class MailInput(MailSettings):
    password: SecretStr | None = None


async def _platform(db: AsyncSession) -> PlatformSettings:
    row = await db.get(PlatformSettings, 1)
    if row is None:
        row = PlatformSettings(id=1)
        db.add(row)
        await db.flush()
    return row


async def mail_settings(db: AsyncSession) -> tuple[MailSettings | None, dict[str, Any]]:
    """The relay (None when not set up) and its secret metadata (ref, last 4)."""
    row = await db.get(PlatformSettings, 1)
    raw = dict((row.extra or {}).get("smtp") or {}) if row else {}
    meta = {k: raw.pop(k) for k in ("secret_ref", "secret_last4") if k in raw}
    return (MailSettings.model_validate(raw) if raw else None), meta


async def save_mail(
    db: AsyncSession, ctx: RequestContext, secrets: SecretWriter | None, data: MailInput
) -> MailSettings:
    row = await _platform(db)
    _, meta = await mail_settings(db)
    if data.password is not None:
        if secrets is None:
            raise NotifyError("the secret store is not available")
        ref = await secrets.put(SMTP_PATH, data.password.get_secret_value())
        if (previous := ref.previous()) is not None:
            await secrets.destroy_version(previous)
        meta = {"secret_ref": ref.ref, "secret_last4": data.password.get_secret_value()[-4:]}
        await audit.record(
            db,
            ctx,
            action="mail.password",
            target_type="platform_setting",
            target_id="smtp",
            after={"secret_last4": meta["secret_last4"]},
        )
    if data.username and not meta.get("secret_ref"):
        raise NotifyError("enter the relay's password")
    settings = MailSettings.model_validate(data.model_dump(exclude={"password"}))
    extra = dict(row.extra or {})
    extra["smtp"] = {**settings.model_dump(mode="json"), **meta}
    await ConfigService(db, ctx).update(row, {"extra": extra}, action="mail.update")
    return settings


async def mail_ready(db: AsyncSession) -> bool:
    settings, _ = await mail_settings(db)
    return settings is not None


# ---------------------------------------------------------------- queueing


def _queue(**values: Any) -> Delivery:
    return Delivery(status=DeliveryStatus.QUEUED, attempts=0, **values)


async def teams_chat_of(db: AsyncSession, user_id: UUID) -> ChannelDestination | None:
    """The person's own chat with a bot (the most recent one they used)."""
    row: ChannelDestination | None = await db.scalar(
        sa.select(ChannelDestination)
        .where(
            ChannelDestination.user_id == user_id,
            ChannelDestination.kind == DestinationKind.TEAMS_CHAT,
            ChannelDestination.removed_at.is_(None),
        )
        .order_by(ChannelDestination.updated_at.desc())
        .limit(1)
    )
    return row


async def notify_user(
    db: AsyncSession,
    user_id: UUID,
    *,
    kind: str,
    title: str,
    body: str = "",
    link: str | None = None,
    card: dict[str, Any] | None = None,
    run_id: UUID | None = None,
) -> Notification:
    user = await db.get(User, user_id)
    if user is None:
        raise NotifyError("unknown person")
    note = Notification(
        user_id=user_id, kind=kind, title=title[:255], body=body[:MAX_TEXT], link=link
    )
    db.add(note)
    await db.flush()
    prefs = user.preferences or {}
    text = f"{title}\n\n{body}".strip()[:MAX_TEXT]
    if user.is_service or user.suspended:
        return note
    if prefs.get("notify_teams", True) and (chat := await teams_chat_of(db, user_id)):
        db.add(
            _queue(
                via=DestinationKind.TEAMS_CHAT.value,
                destination_id=chat.id,
                user_id=user_id,
                text=text,
                card={**(card or {}), "link": link} if link or card else {},
                run_id=run_id,
                notification_id=note.id,
            )
        )
    if prefs.get("notify_email", True) and user.email and await mail_ready(db):
        db.add(
            _queue(
                via="email",
                user_id=user_id,
                address=user.email,
                subject=title[:255],
                text=text,
                card={"link": link} if link else {},
                run_id=run_id,
                notification_id=note.id,
            )
        )
    await db.flush()
    return note


async def queue_post(
    db: AsyncSession,
    *,
    via: str,
    text: str,
    run_id: UUID | None,
    destination_id: UUID | None = None,
    to: list[str] | None = None,
    subject: str = "",
) -> list[Delivery]:
    """An automation's message. Teams chats need the person to have one with a bot."""
    out: list[Delivery] = []
    text = text[:MAX_TEXT]
    if via in {DestinationKind.TEAMS_CHANNEL.value, DestinationKind.SLACK_CHANNEL.value}:
        dest = await db.get(ChannelDestination, destination_id) if destination_id else None
        if dest is None or dest.removed_at is not None:
            raise NotifyError("the bot is no longer in that channel")
        out.append(_queue(via=via, destination_id=dest.id, text=text, run_id=run_id))
    elif via == DestinationKind.TEAMS_CHAT.value:
        for raw in to or []:
            chat = await teams_chat_of(db, UUID(raw))
            if chat is None:
                raise NotifyError("a recipient has not chatted with the bot in Teams yet")
            out.append(
                _queue(via=via, destination_id=chat.id, user_id=UUID(raw), text=text, run_id=run_id)
            )
    elif via == "email":
        if not await mail_ready(db):
            raise NotifyError("email is not set up (Channels & API → Email)")
        for raw in to or []:
            user = await _user_or_none(db, raw)
            address = user.email if user is not None else raw
            if not address or "@" not in address:
                raise NotifyError("a recipient has no e-mail address")
            out.append(
                _queue(
                    via=via,
                    user_id=user.id if user else None,
                    address=address,
                    subject=subject[:255],
                    text=text,
                    run_id=run_id,
                )
            )
    else:
        raise NotifyError(f"unknown channel {via}")
    db.add_all(out)
    await db.flush()
    return out


async def _user_or_none(db: AsyncSession, raw: str) -> User | None:
    try:
        return await db.get(User, UUID(raw))
    except ValueError:
        return None


def mark_sent(row: Delivery) -> None:
    row.status, row.sent_at, row.error = DeliveryStatus.SENT, datetime.now(UTC), None


RETRY_DELAYS = (30, 300, 1800)


def mark_failed(row: Delivery, error: str) -> None:
    """Try again later, a few times; then it stays failed with the error."""
    row.attempts += 1
    row.error = error[:1000]
    if row.attempts > len(RETRY_DELAYS):
        row.status, row.next_attempt_at = DeliveryStatus.FAILED, None
    else:
        row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=RETRY_DELAYS[row.attempts - 1])


def due(via: tuple[str, ...], now: datetime) -> sa.Select[Delivery]:
    """Queued deliveries to send now, oldest first, claimed with SKIP LOCKED."""
    return (
        sa.select(Delivery)
        .where(
            Delivery.status == DeliveryStatus.QUEUED,
            Delivery.via.in_(via),
            sa.or_(Delivery.next_attempt_at.is_(None), Delivery.next_attempt_at <= now),
        )
        .order_by(Delivery.created_at)
        .limit(20)
        .with_for_update(skip_locked=True)
    )
