"""The channels service: Teams and Slack endpoints (a runtime service; reads its bots'
credentials from OpenBao, never writes secrets)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, Request, Response
from veyntora_api.authz.fga import Authz
from veyntora_api.core.logging import configure_logging
from veyntora_api.settings import get_settings
from veyntora_providers.secrets import OpenBaoReader

from veyntora_channels.core import Runner
from veyntora_channels.slack import Slack
from veyntora_channels.teams import Teams


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.environment != "local")
    http = httpx.AsyncClient()
    authz = await Authz.connect(settings.openfga_url, settings.openfga_store_name)
    reader = OpenBaoReader(settings.openbao_url, Path(settings.openbao_token_file))
    runner = Runner(settings, authz, http)
    app.state.teams = Teams(runner, reader)
    app.state.slack = Slack(runner, reader)
    try:
        yield
    finally:
        await authz.close()
        await http.aclose()


app = FastAPI(title="Veyntora channels", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/teams/messages", include_in_schema=False)
async def teams_messages(request: Request) -> Response:
    teams: Teams = request.app.state.teams
    return await teams.handle(request)


@app.post("/slack/events", include_in_schema=False)
async def slack_events(request: Request, background: BackgroundTasks) -> Response:
    slack: Slack = request.app.state.slack
    return await slack.handle(request, background)
