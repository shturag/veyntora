"""SharePoint connector against a mocked Microsoft Graph (respx) and a real database.

No live tenant is involved; the Graph responses follow the documented shapes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.governance import AuditEvent
from veyntora_api.db.models.knowledge import Document, DocumentStatus, IngestJob, IngestJobKind
from veyntora_api.knowledge import service as knowledge
from veyntora_api.routers.admin_sources import _sharepoint
from veyntora_workers.connectors.sync import sync_sharepoint
from veyntora_workers.sources import cron_matches

from tests.test_ingestion import CTX, POLICY, World, _bot_with_source

GRAPH = "https://graph.microsoft.com/v1.0"
SECRET = "sp-secret-0123456789-ABCD"
ENTRA_GROUP = "11111111-2222-3333-4444-555555555555"


class Writer:
    def __init__(self) -> None:
        self.stored: dict[str, str] = {}

    async def put(self, path: str, value: str, expires_at: datetime | None = None) -> Any:
        from veyntora_api.secrets.openbao import SecretRef, last4  # noqa: PLC0415

        self.stored[path] = value
        return SecretRef(f"kv/{path}", last4(value), expires_at)


class Reader:
    def __init__(self, writer: Writer) -> None:
        self.writer = writer

    async def read(self, ref: str) -> str:
        return self.writer.stored[ref.removeprefix("kv/")]


def _item(item_id: str, name: str, folder: str = "Policies", **extra: Any) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": name,
        "file": {"mimeType": "text/markdown"},
        "size": 120,
        "cTag": f"c-{item_id}-1",
        "webUrl": f"https://contoso.sharepoint.com/sites/kb/{folder}/{name}",
        "lastModifiedDateTime": "2026-10-01T08:00:00Z",
        "parentReference": {"path": f"/drives/d1/root:/{folder}"},
        **extra,
    }


def _mock_graph(mock: respx.MockRouter, items: list[dict[str, Any]], delta_link: str) -> None:
    mock.post(url__regex=r"https://login\.microsoftonline\.com/.*/token").respond(
        json={"access_token": "token-1", "expires_in": 3600}
    )
    mock.get(f"{GRAPH}/sites/contoso.sharepoint.com:/sites/kb").respond(json={"id": "site-1"})
    mock.get(f"{GRAPH}/sites/site-1/drives").respond(
        json={"value": [{"id": "d1", "name": "Documents"}]}
    )
    mock.get(url__regex=rf"{GRAPH}/drives/d1/root/delta.*").respond(
        json={"value": items, "@odata.deltaLink": delta_link}
    )
    mock.get(url__regex=rf"{GRAPH}/drives/d1/items/.*/content").respond(content=POLICY)
    mock.get(url__regex=rf"{GRAPH}/drives/d1/items/.*/permissions").respond(
        json={
            "value": [
                {"grantedToV2": {"group": {"id": ENTRA_GROUP, "displayName": "Support"}}},
                {"grantedToV2": {"user": {"email": "A@example.com", "displayName": "A"}}},
                {"grantedToV2": {"siteGroup": {"displayName": "KB Visitors"}}},
                {"link": {"scope": "anonymous"}, "grantedToIdentitiesV2": []},
            ]
        }
    )


@pytest.fixture
async def setup(db: AsyncSession) -> tuple[World, Any, Writer]:
    w = await World(db).setup()
    writer = Writer()
    source = await knowledge.create_sharepoint_source(
        db,
        CTX,
        writer,  # type: ignore[arg-type]
        knowledge.SharePointSourceInput(
            name=f"KB {uuid4().hex[:6]}",
            settings=knowledge.SharePointSettings(
                tenant_id="contoso.onmicrosoft.com",
                client_id=uuid4(),
                site_url="https://contoso.sharepoint.com/sites/kb",
                include_paths=["Documents/Policies"],
                group_map={f"entra:{ENTRA_GROUP}": w.group.id},
            ),
            client_secret=SecretStr(SECRET),
            schedule="0 */4 * * *",
        ),
        w.user.id,
    )
    bot, _ = await _bot_with_source(w)
    from veyntora_api.chatbots import service as bots  # noqa: PLC0415

    await bots.set_sources(db, CTX, bot, [bots.Attachment(source_id=source.id)], w.user.id)
    return w, source, writer


async def test_secret_is_write_only(setup: tuple[World, Any, Writer], db: AsyncSession) -> None:
    _, source, writer = setup
    assert writer.stored == {f"sources/{source.id}": SECRET}
    assert SECRET not in str(source.config)
    out = _sharepoint(source)
    assert out is not None and out.has_secret and out.secret_last4 == "ABCD"
    assert SECRET not in out.model_dump_json()
    events = (
        await db.execute(sa.select(AuditEvent).where(AuditEvent.target_id == str(source.id)))
    ).scalars()
    assert all(SECRET not in str(e.after) for e in events)


async def test_sync_maps_permissions_and_fails_closed(setup: tuple[World, Any, Writer]) -> None:
    w, source, writer = setup
    ing = w.ingestor()
    ing.secrets = Reader(writer)  # type: ignore[assignment]
    with respx.mock(assert_all_called=False) as mock:
        _mock_graph(
            mock,
            [
                _item("i1", "refund-policy.md"),
                _item("i2", "notes.md", folder="Private"),  # outside the include paths
                _item("i3", "tool.exe"),
                {"id": "f1", "name": "Policies", "folder": {}},
            ],
            f"{GRAPH}/drives/d1/root/delta?token=abc",
        )
        stats = await sync_sharepoint(ing, source)

    assert stats["changed"] == 1 and stats["skipped"] == 1 and stats["unsupported"] == 1
    doc = await w.db.scalar(
        sa.select(Document).where(Document.source_id == source.id, Document.external_id == "d1/i1")
    )
    assert doc is not None and doc.path == "Documents/Policies/refund-policy.md"
    assert doc.acl == {"users": [str(w.user.id)], "groups": [str(w.group.id)]}
    assert doc.status is DocumentStatus.INDEXED, "indexed in the same sync"
    assert {
        p.payload["acl"] == [f"user:{w.user.id}", f"group:{w.group.id}"]
        for p in w.vectors.of(doc.id)
    } == {True}
    assert set(source.config["unmapped"]) == {"site:KB Visitors", "sharing link (anonymous)"}
    assert source.config["state"]["delta"]["d1"].endswith("token=abc")


async def test_changed_and_deleted_items(setup: tuple[World, Any, Writer]) -> None:
    w, source, writer = setup
    ing = w.ingestor()
    ing.secrets = Reader(writer)  # type: ignore[assignment]
    with respx.mock(assert_all_called=False) as mock:
        _mock_graph(mock, [_item("i1", "refund-policy.md")], f"{GRAPH}/drives/d1/root/delta?t=1")
        await sync_sharepoint(ing, source)
    with respx.mock(assert_all_called=False) as mock:
        _mock_graph(mock, [_item("i1", "refund-policy.md")], f"{GRAPH}/drives/d1/root/delta?t=2")
        stats = await sync_sharepoint(ing, source)
        assert stats.get("unchanged") == 1, "same cTag: nothing is downloaded again"
    with respx.mock(assert_all_called=False) as mock:
        _mock_graph(
            mock,
            [{"id": "i1", "deleted": {"state": "deleted"}}],
            f"{GRAPH}/drives/d1/root/delta?t=3",
        )
        stats = await sync_sharepoint(ing, source)
    assert stats["deleted"] == 1
    doc = await w.db.scalar(sa.select(Document).where(Document.external_id == "d1/i1"))
    assert doc is not None and doc.status is DocumentStatus.DELETED
    job = await w.db.scalar(
        sa.select(IngestJob).where(
            IngestJob.document_id == doc.id, IngestJob.kind == IngestJobKind.DELETE
        )
    )
    assert job is not None


async def test_bad_credentials_say_why(setup: tuple[World, Any, Writer]) -> None:
    w, source, writer = setup
    ing = w.ingestor()
    ing.secrets = Reader(writer)  # type: ignore[assignment]
    with respx.mock() as mock:
        mock.post(url__regex=r"https://login\.microsoftonline\.com/.*").respond(
            400, json={"error": "invalid_client", "error_description": f"secret {SECRET} bad"}
        )
        with pytest.raises(Exception, match="invalid_client") as err:
            await sync_sharepoint(ing, source)
    assert SECRET not in str(err.value), "Entra's description can echo the request"


async def test_group_map_and_schedule_are_validated(setup: tuple[World, Any, Writer]) -> None:
    w, source, _ = setup
    bad = knowledge.SharePointSettings.model_validate(
        {
            **{k: source.config[k] for k in ("tenant_id", "client_id", "site_url")},
            "group_map": {"x": str(w.group.id)},
        }
    )
    with pytest.raises(knowledge.KnowledgeError, match="entra: or site:"):
        await knowledge.update_source(
            w.db, CTX, source, knowledge.SourceUpdate(sharepoint=bad), expected_version=None
        )
    with pytest.raises(knowledge.KnowledgeError, match="schedules"):
        await knowledge.update_source(
            w.db, CTX, source, knowledge.SourceUpdate(schedule="* * * * *"), expected_version=None
        )


def test_cron_matcher() -> None:
    at = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)
    assert cron_matches("0 * * * *", at)
    assert cron_matches("0 */4 * * *", at)
    assert not cron_matches("0 */4 * * *", at.replace(hour=9))
    assert cron_matches("0 6 * * *", at.replace(hour=6))
    assert not cron_matches("0 6 * * *", at.replace(minute=1, hour=6))
    assert not cron_matches("bogus", at)


def test_site_address_must_be_sharepoint() -> None:
    with pytest.raises(ValueError):
        knowledge.SharePointSettings(
            tenant_id="contoso", client_id=uuid4(), site_url="http://evil.example/sites/kb"
        )
    assert httpx  # used by respx fixtures
