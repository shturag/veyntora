"""What the API serves until Veyntora is set up and bootstrapped (ADR 0034).

    veyntora-api serve-setup     (started by the launcher, never on its own)

Only the Setup page's endpoints. They need the setup code, which is printed in the API's
log and kept on the config volume until Veyntora is running; ten wrong codes replace it.
Every other path answers 503 so the web app shows the Setup page.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Literal

import structlog
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from veyntora_api.infra import checks, service, vault
from veyntora_api.infra import config as c
from veyntora_api.infra.launcher import SETUP_ERROR_ENV, current_tag
from veyntora_api.infra.service import CheckOut, InfraError, SetupCheckError, SetupIn, TestIn

log = structlog.get_logger()

_MAX_WRONG = 10
State = Literal["setup", "starting", "failed", "ready"]


class VersionOut(BaseModel):
    version: int
    saved_at: datetime
    saved_by: str


class SetupStateOut(BaseModel):
    state: State
    # Why starting failed (migrate's last error), in words; never a password.
    error: str | None = None
    version: int | None = None
    # Set up before: the Setup page only offers going back to an earlier version.
    set_up: bool = False
    # Prefilled for a second try: the settings saved last time (no passwords).
    saved: dict[str, dict[str, object]] | None = None
    # When starting failed after a change: the versions it can go back to.
    earlier: list[VersionOut] = []


class CodeIn(BaseModel):
    code: str


class RestoreIn(CodeIn):
    version: int


class SetupTestIn(TestIn):
    code: str


class SetupOut(BaseModel):
    state: State
    results: dict[str, CheckOut] | None = None


class Codes:
    def __init__(self, store: c.Store) -> None:
        self.store = store
        self.wrong = 0
        self.code = self._load() or self.rotate()

    def _load(self) -> str | None:
        try:
            return self.store.setup_code.read_text().strip() or None
        except FileNotFoundError:
            return None

    def rotate(self) -> str:
        code = "-".join(secrets.token_hex(3) for _ in range(3))
        self.store.root.mkdir(parents=True, exist_ok=True)
        path = self.store.setup_code
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(code)
        self.code = code
        self.wrong = 0
        return code

    def announce(self) -> None:
        # By design: whoever can read the API's log may set Veyntora up.
        log.warning("setup.code", code=self.code, hint="enter it on the Setup page (/setup)")

    def check(self, given: str) -> None:
        if secrets.compare_digest(given.strip().lower(), self.code):
            return
        self.wrong += 1
        log.warning("setup.wrong_code", attempts=self.wrong)
        if self.wrong >= _MAX_WRONG:
            self.rotate()
            self.announce()
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="wrong setup code")


def state_of(store: c.Store) -> SetupStateOut:
    cfg = store.load()
    if cfg is None:
        return SetupStateOut(state="setup")
    set_up = store.is_set_up()
    marker = store.read_marker()
    error = os.environ.get(SETUP_ERROR_ENV) or None
    if marker and marker.version == current_tag(store):
        if marker.ok and not error:
            return SetupStateOut(state="ready", version=cfg.version, set_up=set_up)
        error = error or marker.error or "bootstrap failed"
    earlier = [
        VersionOut(version=v.version, saved_at=v.saved_at, saved_by=v.saved_by)
        for v in store.versions()
        if v.version != cfg.version
    ]
    return SetupStateOut(
        state="failed" if error else "starting",
        error=error,
        version=cfg.version,
        set_up=set_up,
        saved=None if set_up else {s: cfg.section(s).model_dump(mode="json") for s in c.SERVICES},
        earlier=earlier if error and set_up else [],
    )


def _not_set_up_yet(store: c.Store) -> None:
    if store.is_set_up():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Veyntora is set up already: change it in Admin, Infrastructure",
        )


def create_setup_app(store: c.Store | None = None) -> FastAPI:
    store = store or c.Store()
    codes = Codes(store)
    app = FastAPI(title="Veyntora setup", docs_url=None, redoc_url=None, openapi_url=None)
    codes.announce()

    @app.middleware("http")
    async def headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    @app.get("/healthz")
    @app.get("/readyz")
    async def health() -> dict[str, str]:
        # The web app starts against this; the Setup page is all it can show.
        return {"status": "setup"}

    @app.get("/v1/setup")
    async def get_state() -> SetupStateOut:
        return state_of(store)

    @app.post("/v1/setup/code", status_code=204)
    async def check_code(data: CodeIn) -> None:
        codes.check(data.code)

    @app.post("/v1/setup/test")
    async def test(data: SetupTestIn) -> CheckOut:
        codes.check(data.code)
        _not_set_up_yet(store)
        try:
            section = service.section_of(data.service, data.settings)
            given = service.plain(data.secrets)
            service.check_secret_names(given, complete=False)
        except (InfraError, ValueError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        admin = data.openbao_admin_token.get_secret_value() if data.openbao_admin_token else None
        if data.service == "openbao" and not admin:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="enter an OpenBao admin token"
            )
        result = await checks.run(section, given, admin_token=admin)
        return CheckOut(ok=result.ok, detail=result.detail)

    @app.post("/v1/setup")
    async def setup(data: SetupIn) -> SetupOut:
        codes.check(data.code)
        _not_set_up_yet(store)
        try:
            cfg = await service.first_setup(data, store)
        except SetupCheckError as exc:
            return SetupOut(
                state=state_of(store).state,
                results={s: CheckOut(ok=False, detail=d) for s, d in exc.failed.items()},
            )
        except (InfraError, vault.VaultError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        log.info("setup.saved", version=cfg.version)
        return SetupOut(state="starting")

    @app.post("/v1/setup/restore")
    async def restore(data: RestoreIn) -> SetupOut:
        """Starting failed after a change: go back to a version that worked."""
        codes.check(data.code)
        cfg = store.load()
        if cfg is None or state_of(store).state != "failed":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="nothing to go back from")
        try:
            saved = service.restore(cfg, store, data.version, saved_by="Setup page (go back)")
        except InfraError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        log.warning("setup.restored", version=data.version, as_version=saved.version)
        return SetupOut(state="starting")

    @app.api_route(
        "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False
    )
    async def not_set_up(path: str) -> JSONResponse:
        return JSONResponse(
            {"detail": "Veyntora is not set up yet", "setup": state_of(store).state},
            status_code=503,
        )

    return app
