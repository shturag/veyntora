"""The virus scanner uploads are checked with (clamd, ADR 0033): its address is a platform
setting, changed in the admin console (Integrations). VEY_CLAMAV_ADDRESS only seeds it once.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from veyntora_api.core.config_service import ConfigService
from veyntora_api.core.context import RequestContext
from veyntora_api.db.models.platform import PlatformSettings
from veyntora_api.knowledge import clamd


class ScannerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # host:port of clamd (e.g. host.docker.internal:3310).
    address: str = Field(min_length=3, max_length=255, pattern=r"^[A-Za-z0-9.-]+:\d{1,5}$")


async def scanner_address(db: AsyncSession) -> str:
    """The configured address, or "" when no scanner is set up."""
    row = await db.get(PlatformSettings, 1)
    raw = (row.extra or {}).get("scanner") if row else None
    return str(raw.get("address", "")) if isinstance(raw, dict) else ""


async def save_scanner(db: AsyncSession, ctx: RequestContext, data: ScannerSettings | None) -> None:
    """Set the scanner, or remove it (None). Audited like every setting."""
    row = await db.get(PlatformSettings, 1)
    if row is None:
        row = PlatformSettings(id=1)
        db.add(row)
        await db.flush()
    extra = dict(row.extra or {})
    if data is None:
        extra.pop("scanner", None)
    else:
        extra["scanner"] = data.model_dump(mode="json")
    await ConfigService(db, ctx).update(
        row, {"extra": extra}, action="scanner.update" if data else "scanner.remove"
    )


async def check(address: str) -> tuple[bool, str]:
    """Whether clamd answers PING at `address`."""
    if await clamd.ping(address):
        return True, "clamd answered"
    return False, f"no answer from clamd at {address}"
