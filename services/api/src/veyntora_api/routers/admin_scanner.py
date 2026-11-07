"""The virus scanner uploads are checked with (ADR 0033): its address, and "Test connection".

Shown on Integrations; changing it needs editor rights on Data sources, whose uploads it
guards.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from veyntora_api.auth.deps import Ctx, DbSession, Principal, State, require_admin_area
from veyntora_api.knowledge import scanner

router = APIRouter(prefix="/v1/admin/scanner", tags=["admin: data sources"])

Viewer = Annotated[Principal, Depends(require_admin_area("sources", "viewer"))]
Editor = Annotated[Principal, Depends(require_admin_area("sources", "editor"))]


class ScannerOut(BaseModel):
    address: str | None
    # Uploads wait (or are refused) while scanning is required and no scanner is set up.
    required: bool


class CheckOut(BaseModel):
    ok: bool
    detail: str


async def _out(db: DbSession, state: State) -> ScannerOut:
    address = await scanner.scanner_address(db)
    return ScannerOut(address=address or None, required=state.settings.scan_required)


@router.get("", summary="The virus scanner")
async def get_scanner(_: Viewer, db: DbSession, state: State) -> ScannerOut:
    return await _out(db, state)


@router.put("", summary="Set the virus scanner's address")
async def put_scanner(
    data: scanner.ScannerSettings, _: Editor, db: DbSession, ctx: Ctx, state: State
) -> ScannerOut:
    await scanner.save_scanner(db, ctx, data)
    await db.commit()
    return await _out(db, state)


@router.delete("", summary="Remove the virus scanner")
async def delete_scanner(_: Editor, db: DbSession, ctx: Ctx, state: State) -> ScannerOut:
    await scanner.save_scanner(db, ctx, None)
    await db.commit()
    return await _out(db, state)


@router.post("/test", summary="Check that the scanner answers")
async def test_scanner(data: scanner.ScannerSettings, _: Editor) -> CheckOut:
    ok, detail = await scanner.check(data.address)
    return CheckOut(ok=ok, detail=detail)
