"""Automation jobs: the scheduler tick, starting queued runs on the graph server,
resuming runs once their approval is decided (with escalation on timeout), and email.

Runs start with an API-signed token for the automation's service identity, never a
person's, so a run can do exactly what that identity was granted.
"""

from __future__ import annotations

import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.agent import approvals
from veyntora_api.auth import internal
from veyntora_api.authz.fga import Authz
from veyntora_api.automations import runs as run_records
from veyntora_api.automations import triggers
from veyntora_api.db.models.automations import (
    Approval,
    ApprovalDecision,
    Automation,
    Run,
    RunKind,
    RunStatus,
)
from veyntora_api.db.models.identity import User
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.notify import service as notify
from veyntora_api.settings import Settings
from veyntora_providers.secrets import OpenBaoReader, SecretReader, SecretUnavailableError

log = structlog.get_logger()
GRAPH = "automation"


def _token(settings: Settings, user: User) -> str:
    return internal.mint(
        settings.internal_token_secret.get_secret_value(), user.keycloak_sub, "automation"
    )


async def _identity(db: AsyncSession, run: Run) -> User | None:
    automation = await db.get(Automation, run.automation_id) if run.automation_id else None
    if automation is None or automation.service_user_id is None:
        return None
    user = await db.get(User, automation.service_user_id)
    return None if user is None or user.suspended else user


# ---------------------------------------------------------------- scheduler tick


async def tick(settings: Settings, now: datetime | None = None) -> int:
    """Queue scheduled runs and check watchers whose time has come."""
    now = now or datetime.now(UTC)
    count = 0
    async with get_sessionmaker()() as db:
        count += len(await triggers.due_schedules(db, now))
        await db.commit()
        watchers = await triggers.due_watchers(db, now)
        if watchers:
            authz = await Authz.connect(settings.openfga_url, settings.openfga_store_name)
            reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
            try:
                for row in watchers:
                    fired = await triggers.watch(db, authz, reader, row, now)
                    if fired.skipped:
                        log.warning("automation.watch_skipped", id=str(row.id), why=fired.skipped)
                    count += len(fired.runs)
            finally:
                await authz.close()
        await db.commit()
    return count


# ---------------------------------------------------------------- start and resume


async def _post(
    http: httpx.AsyncClient, settings: Settings, token: str, path: str, body: dict[str, Any]
) -> Any:
    res = await http.post(
        f"{settings.graphs_url.rstrip('/')}/{path}",
        json=body,
        headers={"authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    res.raise_for_status()
    return res.json()


async def start_queued(settings: Settings, http: httpx.AsyncClient, limit: int = 10) -> int:
    started = 0
    async with get_sessionmaker()() as db:
        rows = (
            await db.execute(
                sa.select(Run)
                .where(Run.kind == RunKind.AUTOMATION, Run.status == RunStatus.QUEUED)
                .order_by(Run.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
        for run in rows:
            user = await _identity(db, run)
            if user is None:
                await run_records.finish(
                    db, run, outcome="failed", error="The service identity is not available."
                )
                continue
            token = _token(settings, user)
            try:
                thread = await _post(http, settings, token, "threads", {})
                run.thread_id = str(thread["thread_id"])
                run.status = RunStatus.RUNNING
                await db.commit()
                await _post(
                    http,
                    settings,
                    token,
                    f"threads/{run.thread_id}/runs",
                    {"assistant_id": GRAPH, "input": {"run_id": str(run.id)}},
                )
                started += 1
            except httpx.HTTPError as exc:
                log.warning("automation.start_failed", run_id=str(run.id), error=str(exc))
                await run_records.finish(
                    db, run, outcome="failed", error="The run could not be started."
                )
            await db.commit()
    return started


async def escalate(db: AsyncSession, authz: Any, now: datetime) -> int:
    """Approvals past their time that escalate: once, to the escalation group."""
    rows = (
        await db.execute(
            sa.select(Approval)
            .where(
                Approval.decision == ApprovalDecision.PENDING,
                Approval.on_timeout == "escalate",
                Approval.escalated_at.is_(None),
                Approval.escalate_group_id.is_not(None),
                Approval.expires_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    count = 0
    for row in rows:
        ttl = (row.expires_at or now) - row.created_at
        row.approver_group_id, row.escalated_at = row.escalate_group_id, now
        row.expires_at = now + ttl
        await run_records.tell_approvers(db, authz, row)
        count += 1
    return count


def _ready(row: Approval, run: Run) -> bool:
    """Decided, timed out, or its run was cancelled, and not resumed for it yet."""
    if run.checkpoint_id == str(row.id):
        return False
    return run.status is RunStatus.CANCELLED or (
        approvals.current(row) is not ApprovalDecision.PENDING
    )


async def resume_decided(settings: Settings, http: httpx.AsyncClient) -> int:
    resumed = 0
    now = datetime.now(UTC)
    async with get_sessionmaker()() as db:
        authz = await Authz.connect(settings.openfga_url, settings.openfga_store_name)
        try:
            await escalate(db, authz, now)
            await db.commit()
        finally:
            await authz.close()
        latest = (
            sa.select(Approval.run_id, sa.func.max(Approval.created_at).label("at"))
            .group_by(Approval.run_id)
            .subquery()
        )
        pairs = (
            await db.execute(
                sa.select(Approval, Run)
                .join(Run, Run.id == Approval.run_id)
                .join(
                    latest,
                    sa.and_(latest.c.run_id == Approval.run_id, latest.c.at == Approval.created_at),
                )
                .where(
                    Run.kind == RunKind.AUTOMATION,
                    Run.status.in_([RunStatus.WAITING_APPROVAL, RunStatus.CANCELLED]),
                    Run.thread_id.is_not(None),
                )
                .order_by(Approval.created_at)
                .limit(50)
            )
        ).all()
        for row, run in pairs:
            if not _ready(row, run):
                continue
            user = await _identity(db, run)
            if user is None:
                continue
            run.checkpoint_id = str(row.id)
            await db.commit()
            command = (
                {"cancel": True}
                if run.status is RunStatus.CANCELLED
                else {"approval_id": str(row.id)}
            )
            try:
                await _post(
                    http,
                    settings,
                    _token(settings, user),
                    f"threads/{run.thread_id}/runs",
                    {"assistant_id": GRAPH, "command": {"resume": command}},
                )
                resumed += 1
            except httpx.HTTPError as exc:
                log.warning("automation.resume_failed", run_id=str(run.id), error=str(exc))
                run.checkpoint_id = None
                await db.commit()
    return resumed


# ---------------------------------------------------------------- email


def _send(settings: notify.MailSettings, password: str | None, msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    if settings.security == "tls":
        with smtplib.SMTP_SSL(settings.host, settings.port, context=context, timeout=20) as s:
            if settings.username:
                s.login(settings.username, password or "")
            s.send_message(msg)
        return
    with smtplib.SMTP(settings.host, settings.port, timeout=20) as s:
        if settings.security == "starttls":
            s.starttls(context=context)
        if settings.username:
            s.login(settings.username, password or "")
        s.send_message(msg)


def _message(
    settings: notify.MailSettings, to: str, *, subject: str, text: str, link: str | None, base: str
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{settings.from_name} <{settings.from_address}>"
    msg["To"] = to
    msg["Subject"] = subject or "Veyntora"
    body = text
    if link:
        body += f"\n\nOpen in Veyntora: {base.rstrip('/')}{link}"
    msg.set_content(body)
    return msg


async def send_email(settings: Settings, reader: SecretReader | None = None) -> int:
    """Send queued emails through the relay (Channels & API → Email)."""
    sent = 0
    async with get_sessionmaker()() as db:
        relay, meta = await notify.mail_settings(db)
        rows = list((await db.execute(notify.due(("email",), datetime.now(UTC)))).scalars())
        if not rows:
            return 0
        password = None
        if relay is not None and relay.username and meta.get("secret_ref"):
            reader = reader or OpenBaoReader(
                settings.openbao_url, Path(settings.openbao_token_file)
            )
            try:
                password = await reader.read(str(meta["secret_ref"]))
            except SecretUnavailableError as exc:
                relay = None
                log.warning("email.no_password", error=str(exc))
        for row in rows:
            if relay is None:
                notify.mark_failed(row, "email is not set up")
                continue
            msg = _message(
                relay,
                row.address or "",
                subject=row.subject,
                text=row.text,
                link=(row.card or {}).get("link"),
                base=settings.public_base_url,
            )
            try:
                _send(relay, password, msg)
                notify.mark_sent(row)
                sent += 1
            except (OSError, smtplib.SMTPException) as exc:
                notify.mark_failed(row, f"{type(exc).__name__}: {exc}")
        await db.commit()
    return sent
