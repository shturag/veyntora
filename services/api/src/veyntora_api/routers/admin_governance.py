"""Governance (prototype: Governance.html).

Viewing needs the Governance area (viewer). Settings need its editors (platform admins,
security reviewers). Legal holds are placed and lifted only by the Legal role; platform
roles are granted only by platform admins.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from veyntora_api.auth.deps import (
    Ctx,
    CurrentPrincipal,
    DbSession,
    Principal,
    State,
    platform_roles,
    require_admin_area,
)
from veyntora_api.core import audit
from veyntora_api.db.models.chatbots import Chatbot
from veyntora_api.db.models.governance import (
    GdprKind,
    GdprRequest,
    GdprStatus,
    GovernanceRule,
    LegalHold,
)
from veyntora_api.db.models.identity import Group, User
from veyntora_api.db.models.providers import ProviderInstance
from veyntora_api.governance import requests as dsr
from veyntora_api.governance import service as svc
from veyntora_api.storage import ObjectStore

router = APIRouter(prefix="/v1/admin/governance", tags=["admin: governance"])

Viewer = Annotated[Principal, Depends(require_admin_area("governance", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("governance", "editor"))]


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


class GovRef(BaseModel):
    id: UUID
    name: str


class HoldOut(BaseModel):
    id: UUID
    name: str
    reason: str
    people: list[str]
    chatbots: list[str]
    created_at: datetime
    released_at: datetime | None


class BotRule(BaseModel):
    id: UUID
    name: str
    external: list[str]
    mask: bool
    chat_retention_days: int | None
    # Traces may go to Langfuse when it is external (it receives them only then).
    external_traces: bool = False


class RoleOut(BaseModel):
    role: str
    groups: list[GovRef]


class GovernancePage(BaseModel):
    settings: svc.GovernanceSettings
    holds: list[HoldOut]
    roles: list[RoleOut]
    chatbots: list[BotRule]
    groups: list[GovRef]
    can_edit: bool
    can_hold: bool
    can_grant: bool
    can_handle_requests: bool


async def _hold_out(db: DbSession, h: LegalHold) -> HoldOut:
    scope = h.scope or {}
    users = [await db.get(User, UUID(str(u))) for u in scope.get("user_ids", [])]
    bots = [await db.get(Chatbot, UUID(str(b))) for b in scope.get("chatbot_ids", [])]
    return HoldOut(
        id=h.id,
        name=h.name,
        reason=h.reason,
        people=[(u.email or u.display_name or str(u.id)) for u in users if u],
        chatbots=[b.name for b in bots if b],
        created_at=h.created_at,
        released_at=h.released_at,
    )


@router.get("", summary="Retention, personal data, holds and roles")
async def overview(principal: Viewer, db: DbSession, state: State) -> GovernancePage:
    authz = state.require_authz()
    roles = await platform_roles(state, principal)
    groups = {g.id: g.name for g in (await db.execute(sa.select(Group))).scalars()}
    holds = (
        (await db.execute(sa.select(LegalHold).order_by(LegalHold.created_at.desc()).limit(50)))
        .scalars()
        .all()
    )
    names = {p.id: p.name for p in (await db.execute(sa.select(ProviderInstance))).scalars()}
    rules = {r.chatbot_id: r for r in (await db.execute(sa.select(GovernanceRule))).scalars()}
    bots = (await db.execute(sa.select(Chatbot).order_by(Chatbot.name))).scalars().all()
    return GovernancePage(
        settings=await svc.settings_of(db),
        holds=[await _hold_out(db, h) for h in holds],
        roles=[
            RoleOut(
                role=role,
                groups=[
                    GovRef(id=g, name=groups.get(g, str(g)))
                    for g in await svc.role_groups(authz, role)
                ],
            )
            for role in svc.GRANTABLE
        ],
        chatbots=[
            BotRule(
                id=b.id,
                name=b.name,
                external=[
                    names.get(i, str(i)) for i in (rules[b.id].allowed_external_instance_ids or [])
                ]
                if b.id in rules
                else [],
                mask=rules[b.id].mask_pii_before_external if b.id in rules else True,
                chat_retention_days=rules[b.id].chat_retention_days if b.id in rules else None,
                external_traces=b.id in rules and rules[b.id].allow_external_traces,
            )
            for b in bots
        ],
        groups=[GovRef(id=i, name=n) for i, n in sorted(groups.items(), key=lambda x: x[1])],
        can_edit=await authz.check(principal.fga, "editor", "admin_area:governance"),
        can_hold=roles["legal"],
        can_grant=roles["platform_admin"],
        can_handle_requests=await _handler(state, principal),
    )


@router.put("/settings", summary="Retention, masking, EU-only, AI notice")
async def save_settings(
    data: svc.GovernanceSettings, _: Editor, ctx: Ctx, db: DbSession
) -> svc.GovernanceSettings:
    await svc.save_settings(db, ctx, data)
    await db.commit()
    return data


async def _legal(state: State, principal: Principal) -> None:
    if not (await platform_roles(state, principal))["legal"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the Legal role may do this")


@router.post("/holds", status_code=status.HTTP_201_CREATED, summary="Place a legal hold")
async def place_hold(
    data: svc.HoldInput, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> HoldOut:
    await _legal(state, principal)
    try:
        row = await svc.place_hold(db, ctx, data, principal.user_id)
    except svc.GovernanceError as exc:
        raise _bad(exc) from exc
    out = await _hold_out(db, row)
    await db.commit()
    return out


@router.post(
    "/holds/{hold_id}/release",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Lift a legal hold",
)
async def release_hold(
    hold_id: UUID, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> Response:
    await _legal(state, principal)
    row = await db.get(LegalHold, hold_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hold not found")
    try:
        await svc.release_hold(db, ctx, row, principal.user_id)
    except svc.GovernanceError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class RoleInput(BaseModel):
    group_ids: list[UUID]


@router.put("/roles/{role}", summary="Groups that hold a platform role")
async def set_role(
    role: svc.Role,
    data: RoleInput,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
) -> RoleOut:
    if not (await platform_roles(state, principal))["platform_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only platform admins grant roles")
    authz = state.require_authz()
    try:
        await svc.set_role_groups(db, ctx, authz, role, data.group_ids)
    except svc.GovernanceError as exc:
        raise _bad(exc) from exc
    await db.commit()
    names = {
        g.id: g.name
        for g in (await db.execute(sa.select(Group).where(Group.id.in_(data.group_ids)))).scalars()
    }
    return RoleOut(role=role, groups=[GovRef(id=g, name=names[g]) for g in data.group_ids])


# ---------------------------------------------------------------- data subject requests


class RequestRow(BaseModel):
    id: UUID
    kind: GdprKind
    subject: str
    status: GdprStatus
    due_at: datetime
    days_left: int
    received_via: str | None
    completed_at: datetime | None
    summary: dict[str, Any]


class FoundOut(BaseModel):
    key: str
    where: str
    amount: int
    action: str


class RequestDetail(RequestRow):
    found: list[FoundOut]
    history: list[dict[str, Any]]
    identity_verified: bool
    approved: bool
    held: bool
    can_handle: bool
    can_approve: bool
    has_report: bool
    has_export: bool


def _masked(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}••••@{domain}"


def _row(r: GdprRequest) -> RequestRow:
    return RequestRow(
        id=r.id,
        kind=r.kind,
        subject=_masked(r.subject_email),
        status=r.status,
        due_at=r.due_at,
        days_left=math.ceil((r.due_at - datetime.now(UTC)).total_seconds() / 86400),
        received_via=r.received_via,
        completed_at=r.completed_at,
        summary=(r.progress or {}).get("found", {}),
    )


async def _handler(state: State, principal: Principal) -> bool:
    """Who may handle requests: Governance editors and data protection officers."""
    roles = await platform_roles(state, principal)
    editor = await state.require_authz().check(principal.fga, "editor", "admin_area:governance")
    return editor or roles["dpo"]


@router.get("/requests", summary="Data subject requests")
async def list_requests(_: Viewer, db: DbSession) -> list[RequestRow]:
    rows = (
        await db.execute(sa.select(GdprRequest).order_by(GdprRequest.created_at.desc()).limit(100))
    ).scalars()
    return [_row(r) for r in rows]


class NewRequest(BaseModel):
    kind: GdprKind
    email: str = Field(min_length=3, max_length=320)
    received_via: str | None = Field(None, max_length=255)
    due_at: datetime | None = None


@router.post("/requests", status_code=status.HTTP_201_CREATED, summary="Record a request")
async def create_request(
    data: NewRequest, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> RequestRow:
    if not await _handler(state, principal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    try:
        row = await dsr.create(
            db,
            ctx,
            kind=data.kind,
            email=data.email,
            received_via=data.received_via,
            due_at=data.due_at,
            by=principal.user_id,
        )
    except dsr.RequestError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return _row(row)


async def _request(db: DbSession, request_id: UUID) -> GdprRequest:
    row = await db.get(GdprRequest, request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return row


@router.get("/requests/{request_id}", summary="One request: what is held, checks, history")
async def get_request(
    request_id: UUID, principal: Viewer, db: DbSession, state: State
) -> RequestDetail:
    r = await _request(db, request_id)
    roles = await platform_roles(state, principal)
    held_users, _ = await svc.held(db)
    found = await dsr.inventory(db, r) if r.status is GdprStatus.RECEIVED else []
    return RequestDetail(
        **_row(r).model_dump(),
        found=[FoundOut(**f.__dict__) for f in found],
        history=list(r.history or []),
        identity_verified=r.identity_verified_at is not None,
        approved=r.approved_at is not None,
        held=r.subject_user_id in held_users,
        can_handle=await _handler(state, principal),
        can_approve=roles["dpo"] and r.requested_by != principal.user_id,
        has_report=r.report_key is not None,
        has_export=str((r.progress or {}).get("export", "")).endswith(".zip"),
    )


Step = Literal["verify", "approve", "carry-out"]


@router.post("/requests/{request_id}/{step}", summary="Verify identity, approve, carry out")
async def request_step(
    request_id: UUID,
    step: Step,
    principal: CurrentPrincipal,
    ctx: Ctx,
    db: DbSession,
    state: State,
) -> RequestRow:
    r = await _request(db, request_id)
    try:
        if step == "approve":
            roles = await platform_roles(state, principal)
            await dsr.approve(db, ctx, r, principal.user_id, is_dpo=roles["dpo"])
        elif not await _handler(state, principal):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        elif step == "verify":
            await dsr.verify_identity(db, ctx, r, principal.user_id)
        else:
            await dsr.carry_out(db, ctx, state.secrets, r, principal.user_id)
    except dsr.RequestError as exc:
        raise _bad(exc) from exc
    await db.commit()
    return _row(r)


async def _download(
    db: DbSession, ctx: Ctx, state: State, r: GdprRequest, key: str, what: str
) -> bytes:
    data = await ObjectStore(state.settings).get(key)
    await audit.record(
        db, ctx, action=f"gdpr.download_{what}", target_type="gdpr_request", target_id=str(r.id)
    )
    await db.commit()
    return data


@router.get(
    "/requests/{request_id}/report",
    summary="The signed confirmation report (JSON)",
    response_class=Response,
)
async def get_report(
    request_id: UUID, principal: Viewer, ctx: Ctx, db: DbSession, state: State
) -> Response:
    r = await _request(db, request_id)
    if not r.report_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No report yet")
    body = await _download(db, ctx, state, r, r.report_key, "report")
    return Response(
        body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="dsr-{str(r.id)[:8]}-report.json"',
            "X-Veyntora-Signature": r.report_signature or "",
        },
    )


@router.get(
    "/requests/{request_id}/export",
    summary="The person's data (ZIP; DPO or the requester)",
    response_class=Response,
)
async def get_export(
    request_id: UUID, principal: CurrentPrincipal, ctx: Ctx, db: DbSession, state: State
) -> Response:
    r = await _request(db, request_id)
    roles = await platform_roles(state, principal)
    if not (roles["dpo"] or r.requested_by == principal.user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    key = str((r.progress or {}).get("export", ""))
    if not key.endswith(".zip"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No export yet")
    body = await _download(db, ctx, state, r, key, "export")
    return Response(
        body,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="dsr-{str(r.id)[:8]}.zip"'},
    )
