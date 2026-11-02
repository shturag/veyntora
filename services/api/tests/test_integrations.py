"""Langfuse and Grafana as configuration (ADR 0024): saving, write-only keys, the runtime
side that uses the key, Grafana panels as data, and traces under the data rule."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
import respx
import sqlalchemy as sa
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.governance import AuditEvent, GovernanceRule
from veyntora_api.db.models.platform import IntegrationKind
from veyntora_api.integrations import runtime, service
from veyntora_api.integrations.service import IntegrationError, IntegrationInput
from veyntora_api.rag import tracing
from veyntora_api.rag.pipeline import load_context
from veyntora_providers.interfaces import Hosting
from veyntora_providers.secrets import SecretUnavailableError

from tests.test_fast_rag import Rag
from tests.test_ingestion import World
from tests.test_providers import CTX, FakeWriter

LF_SECRET = "sk-lf-0123456789abcdefWXYZ"
GF_TOKEN = "glsa_0123456789abcdef_9f2a"


class Writer(FakeWriter):
    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[str] = []

    async def delete(self, path: str) -> None:
        self.deleted.append(path)
        self.stored.pop(path, None)


class Reader:
    def __init__(self, writer: FakeWriter) -> None:
        self.writer = writer

    async def read(self, secret_ref: str) -> str:
        path = secret_ref.removeprefix("kv/")
        if path not in self.writer.stored:
            raise SecretUnavailableError("gone")
        return self.writer.stored[path]


def _langfuse(**kw: Any) -> IntegrationInput:
    return IntegrationInput.model_validate(
        {"url": "http://langfuse:3000/", "public_key": "pk-lf-1", **kw}
    )


def test_input_is_checked() -> None:
    with pytest.raises(ValidationError, match="http"):
        IntegrationInput(url="langfuse:3000")
    with pytest.raises(ValidationError, match="twice"):
        IntegrationInput.model_validate(
            {"url": "http://g", "dashboards": [{"uid": "a", "title": "A"}] * 2}
        )
    with pytest.raises(ValidationError, match="uid"):
        IntegrationInput.model_validate(
            {"url": "http://g", "dashboards": [{"uid": "../x", "title": "X"}]}
        )
    assert _langfuse().url == "http://langfuse:3000"


async def test_kinds_refuse_the_other_kinds_fields(db: AsyncSession) -> None:
    with pytest.raises(IntegrationError, match="no dashboards"):
        await service.save(
            db,
            CTX,
            IntegrationKind.LANGFUSE,
            _langfuse(dashboards=[{"uid": "a", "title": "A"}]),
        )
    with pytest.raises(IntegrationError, match="no public key"):
        await service.save(db, CTX, IntegrationKind.GRAFANA, _langfuse())


async def test_save_store_key_rotate_and_remove(db: AsyncSession) -> None:
    writer = Writer()
    row = await service.save(db, CTX, IntegrationKind.LANGFUSE, _langfuse())
    assert row.version == 1 and row.secret_ref is None
    await service.set_secret(db, CTX, writer, row, value=SecretStr(LF_SECRET), expires_at=None)
    assert writer.stored == {"integrations/langfuse": LF_SECRET}
    assert (row.secret_ref, row.secret_last4) == ("kv/integrations/langfuse", "WXYZ")

    # Rotating destroys the replaced key at once.
    await service.set_secret(
        db, CTX, writer, row, value=SecretStr(LF_SECRET + "2"), expires_at=None
    )
    assert writer.destroyed == ["kv/integrations/langfuse?version=1"]

    # A changed address forgets the last check; the version guards concurrent edits.
    await service.mark_health(db, row, True, "Connected")
    v = row.version
    await service.save(db, CTX, IntegrationKind.LANGFUSE, _langfuse(url="http://lf2"), v)
    assert row.health_ok is None and row.url == "http://lf2"

    actions = (
        await db.execute(
            sa.select(AuditEvent.action, AuditEvent.after).where(
                AuditEvent.target_type == "integration"
            )
        )
    ).all()
    names = [a for a, _ in actions]
    assert names[:3] == [
        "integration.create",
        "integration.secret_set",
        "integration.secret_rotate",
    ]
    # Never the key, only its last 4 characters.
    assert LF_SECRET not in json.dumps([after for _, after in actions], default=str)

    await service.remove(db, CTX, writer, row)
    assert writer.deleted == ["integrations/langfuse"]
    assert await service.get(db, IntegrationKind.LANGFUSE) is None


async def test_resolve_needs_an_enabled_row_with_a_key(db: AsyncSession) -> None:
    writer = Writer()
    reader = Reader(writer)
    assert await runtime.resolve(db, reader, IntegrationKind.LANGFUSE) is None
    row = await service.save(db, CTX, IntegrationKind.LANGFUSE, _langfuse(public_key=None))
    await service.set_secret(db, CTX, writer, row, value=SecretStr(LF_SECRET), expires_at=None)
    # Langfuse without its public key cannot authenticate.
    assert await runtime.resolve(db, reader, IntegrationKind.LANGFUSE) is None
    await service.save(db, CTX, IntegrationKind.LANGFUSE, _langfuse(hosting="external"))
    conn = await runtime.resolve(db, reader, IntegrationKind.LANGFUSE)
    assert conn is not None
    assert (conn.secret, conn.hosting, conn.browser_url) == (
        LF_SECRET,
        Hosting.EXTERNAL,
        "http://langfuse:3000",
    )
    await service.save(db, CTX, IntegrationKind.LANGFUSE, _langfuse(enabled=False))
    assert await runtime.resolve(db, reader, IntegrationKind.LANGFUSE) is None
    # A key that cannot be read means "not available", not a crash.
    await service.save(db, CTX, IntegrationKind.LANGFUSE, _langfuse())
    writer.stored.clear()
    assert await runtime.resolve(db, reader, IntegrationKind.LANGFUSE) is None


def _conn(kind: IntegrationKind, **kw: Any) -> runtime.Connection:
    return runtime.Connection(
        kind=kind,
        hosting=Hosting.SELF_HOSTED,
        url="http://svc",
        browser_url="https://svc.example.com",
        public_key="pk-lf-1" if kind is IntegrationKind.LANGFUSE else None,
        secret=LF_SECRET if kind is IntegrationKind.LANGFUSE else GF_TOKEN,
        **kw,
    )


async def test_checks_use_the_key_and_say_what_is_wrong() -> None:
    with respx.mock(base_url="http://svc") as mock:
        projects = mock.get("/api/public/projects")
        projects.respond(200, json={"data": [{"name": "Veyntora"}]})
        assert await runtime.check(_conn(IntegrationKind.LANGFUSE)) == (
            True,
            "Connected to project Veyntora",
        )
        assert projects.calls.last.request.headers["authorization"].startswith("Basic ")
        projects.respond(401)
        ok, detail = await runtime.check(_conn(IntegrationKind.LANGFUSE))
        assert not ok and "refused the keys" in detail

        search = mock.get("/api/search").respond(200, json=[{"uid": "infra", "title": "Infra"}])
        conn = _conn(IntegrationKind.GRAFANA, dashboards=(("infra", "Infra"), ("gone", "Gone")))
        ok, detail = await runtime.check(conn)
        assert not ok and "gone" in detail
        assert search.calls.last.request.headers["authorization"] == f"Bearer {GF_TOKEN}"

    with respx.mock(base_url="http://svc") as mock:
        mock.get("/api/search").mock(side_effect=httpx.ConnectError("refused"))
        assert await runtime.check(_conn(IntegrationKind.GRAFANA)) == (
            False,
            "Not reachable: ConnectError",
        )


DASHBOARD = {
    "dashboard": {
        "title": "Infrastructure",
        "templating": {
            "list": [
                {"name": "ds", "current": {"value": "prom-uid"}},
                {"name": "job", "current": {"value": ["api", "graphs"]}},
            ]
        },
        "panels": [
            {
                "id": 1,
                "type": "timeseries",
                "title": "Requests ($job)",
                "gridPos": {"w": 12},
                "fieldConfig": {"defaults": {"unit": "reqps"}},
                "datasource": {"type": "prometheus", "uid": "${ds}"},
                "targets": [
                    {
                        "refId": "A",
                        "expr": 'rate(http_requests{job="$job"}[$__rate_interval])',
                    },
                    {"refId": "B", "expr": "hidden", "hide": True},
                ],
            },
            {
                "type": "row",
                "title": "More",
                "panels": [
                    {
                        "id": 2,
                        "type": "stat",
                        "title": "Up",
                        "datasource": {"type": "prometheus", "uid": "prom-uid"},
                        "targets": [{"refId": "A", "expr": "up"}],
                    },
                    {"id": 3, "type": "news", "title": "News"},
                ],
            },
        ],
    },
    "meta": {"url": "/d/infra/infrastructure"},
}


def _frames(name: str, values: list[float | None]) -> dict[str, Any]:
    return {
        "results": {
            "A": {
                "frames": [
                    {
                        "schema": {
                            "fields": [
                                {"name": "Time", "type": "time"},
                                {"name": "Value", "type": "number", "labels": {"job": name}},
                            ]
                        },
                        "data": {"values": [[1000 * i for i in range(len(values))], values]},
                    }
                ]
            }
        }
    }


async def test_dashboard_panels_come_back_as_data() -> None:
    sent: list[dict[str, Any]] = []

    def query(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        sent.append(body)
        expr = body["queries"][0]["expr"]
        return httpx.Response(200, json=_frames("api", [1.0, None, 3.0] if "rate" in expr else [1]))

    with respx.mock(base_url="http://svc") as mock:
        mock.get("/api/dashboards/uid/infra").respond(200, json=DASHBOARD)
        mock.post("/api/ds/query").mock(side_effect=query)
        out = await runtime.dashboard(_conn(IntegrationKind.GRAFANA), "infra", "6h")

    assert out["url"] == "https://svc.example.com/d/infra/infrastructure"
    assert out["end"] - out["start"] == 6 * 3600 * 1000
    ts, stat, other = out["panels"]
    assert (ts["kind"], ts["title"], ts["unit"], ts["width"]) == (
        "timeseries",
        "Requests (api)",
        "reqps",
        12,
    )
    assert ts["series"] == [{"name": "job=api", "points": [(0, 1.0), (1000, None), (2000, 3.0)]}]
    assert stat["kind"] == "stat" and stat["series"][0]["points"] == [(0, 1.0)]
    assert other["kind"] == "unsupported" and other["series"] == []
    first = next(b for b in sent if "rate" in b["queries"][0]["expr"])
    # Variables take their current values; Grafana's own are left for Grafana; hidden
    # queries are not sent.
    assert first["queries"][0]["expr"] == 'rate(http_requests{job="api"}[$__rate_interval])'
    assert first["queries"][0]["datasource"] == {"uid": "prom-uid", "type": "prometheus"}
    assert len(first["queries"]) == 1 and first["from"] == "now-6h"


async def test_a_missing_dashboard_is_reported() -> None:
    with respx.mock(base_url="http://svc") as mock:
        mock.get("/api/dashboards/uid/nope").respond(404)
        with pytest.raises(runtime.GrafanaError, match="not found"):
            await runtime.dashboard(_conn(IntegrationKind.GRAFANA), "nope", "1h")


@pytest.fixture
async def rag(db: AsyncSession) -> Rag:
    return await Rag(await World(db).setup()).setup()


async def test_external_langfuse_traces_only_what_the_data_rule_allows(
    rag: Rag, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = rag.w.db
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    assert ctx.external_traces is False

    tracer = object()
    tracers = tracing._Tracers()
    tracers.tracer, tracers.external = tracer, True  # type: ignore[assignment]
    tracers.checked_at = time.monotonic()  # fresh: no lookup during this test
    monkeypatch.setattr(tracing, "_tracers", tracers)

    trace = await tracing.new_trace(ctx)
    assert trace._tracer is None

    rule = await db.scalar(sa.select(GovernanceRule).where(GovernanceRule.chatbot_id == rag.bot.id))
    keep = {k: getattr(rule, k) for k in bots.GovernanceInput.model_fields} if rule else {}
    await bots.set_governance(
        db, CTX, rag.bot, bots.GovernanceInput(**{**keep, "allow_external_traces": True})
    )
    ctx = await load_context(db, rag.authz, rag.w.user.keycloak_sub, rag.bot.id)
    trace = await tracing.new_trace(ctx)
    assert trace._tracer is tracer and trace.mask is True

    # Self-hosted: every chatbot is traced, masked as the platform setting says.
    tracers.external = False
    trace = await tracing.new_trace(ctx)
    assert trace._tracer is tracer and trace.mask is ctx.mask_traces
