"""Confluence (mocked REST, Cloud and Data Center), databases (PostgreSQL for real; the
read-only query check) and file shares (Samba in a container: listing, NTFS permissions,
download), each through the listing sync with mapped, fail-closed permissions."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import httpx
import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from veyntora_api.db.models.knowledge import DataSource, Document
from veyntora_api.knowledge import connectors
from veyntora_api.knowledge.service import SourceAcl
from veyntora_workers.connectors.confluence import ConfluenceReader
from veyntora_workers.connectors.database import DatabaseReader
from veyntora_workers.connectors.listing import sync_listing
from veyntora_workers.connectors.smb import SmbReader, readers_of

from tests.test_ingestion import CTX, World
from tests.test_sharepoint import Writer

BASE = "https://acme.atlassian.net/wiki"


@pytest.fixture
async def world(db: Any) -> World:
    return await World(db).setup()


async def _source(w: World, kind: str, settings: Any, **extra: Any) -> DataSource:
    return await connectors.create_connected_source(
        w.db,
        CTX,
        Writer(),  # type: ignore[arg-type]
        connectors.ConnectedSourceInput(
            name=f"{kind}-{uuid4().hex[:6]}",
            type=kind,  # type: ignore[arg-type]
            secret="s3cr3t-value-0000",  # type: ignore[arg-type]
            **{kind: settings},
            **extra,
        ),
        w.user.id,
    )


async def _docs(w: World, source: DataSource) -> dict[str, Document]:
    rows = await w.db.execute(sa.select(Document).where(Document.source_id == source.id))
    return {d.path: d for d in rows.scalars()}


# ---------------------------------------------------------------- Confluence


def _page(
    pid: str, title: str, ancestors: list[str], groups: list[str] | None = None
) -> dict[str, Any]:
    read = {"user": {"results": []}, "group": {"results": [{"name": g} for g in groups or []]}}
    return {
        "id": pid,
        "title": title,
        "version": {"number": 3, "when": "2026-10-01T08:00:00.000Z"},
        "body": {"storage": {"value": f"<p>{title} text</p>"}},
        "ancestors": [{"id": a, "title": f"Parent {a}"} for a in ancestors],
        "restrictions": {"read": {"restrictions": read}},
        "_links": {"webui": f"/spaces/HR/pages/{pid}"},
    }


def _perm(kind: str, i: str) -> dict[str, Any]:
    return {
        "principal": {"type": kind, "id": i},
        "operation": {"key": "read", "targetType": "space"},
    }


CLOUD: dict[str, Any] = {
    "/api/v2/spaces": lambda _: {"results": [{"id": "77", "key": "HR"}]},
    "/api/v2/spaces/77/permissions": lambda _: {
        "results": [_perm("group", "g1"), _perm("group", "g2"), _perm("user", "u9")]
    },
    "/rest/api/group/by-id": lambda r: {
        "name": {"g1": "hr-all", "g2": "hr-leads"}[r.url.params["id"]]
    },
    "/rest/api/user": lambda _: {"accountId": "u9"},  # e-mail hidden
    "/rest/api/content": lambda _: {
        "results": [
            _page("1", "Leave policy", []),
            _page("2", "Salaries", [], groups=["hr-leads"]),
            _page("3", "Salary bands", ["2"]),
        ]
    },
    "/rest/api/space/HR": lambda _: {"name": "Human resources"},
}


def _cloud(req: httpx.Request) -> httpx.Response:
    route = CLOUD.get(req.url.path.removeprefix("/wiki"))
    return httpx.Response(200, json=route(req)) if route else httpx.Response(404)


async def test_confluence_maps_space_permissions_and_restrictions(world: World) -> None:
    w = world
    cfg = connectors.ConfluenceSettings(
        base_url=BASE, email="bot@acme.com", spaces=["HR"], group_map={"hr-all": w.group.id}
    )
    source = await _source(w, "confluence", cfg)
    reader = ConfluenceReader(cfg, "token", w.db, transport=httpx.MockTransport(_cloud))
    assert "Human resources" in await reader.check()
    stats = await sync_listing(w.ingestor(), source, reader.listing())
    assert stats["changed"] == 3
    docs = await _docs(w, source)
    assert docs["HR/Leave policy"].acl == {"users": [], "groups": [str(w.group.id)]}
    # Restricted to hr-leads, which is not mapped: nobody may read (fail closed).
    assert docs["HR/Salaries"].acl == {"users": [], "groups": []}
    assert docs["HR/Parent 2/Salary bands"].acl == {"users": [], "groups": []}
    assert {"group hr-leads", "user u9 (e-mail hidden)"} <= set(source.config["unmapped"])


def test_confluence_cloud_needs_an_email() -> None:
    with pytest.raises(ValidationError, match="e-mail"):
        connectors.ConfluenceSettings(base_url=BASE, spaces=["HR"])


async def test_confluence_data_center_space_permissions(world: World) -> None:
    def dc(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer pat-1"
        return httpx.Response(
            200,
            json={
                "permissions": [
                    {
                        "operation": {"operation": "read", "targetType": "space"},
                        "subjects": {
                            "group": {"results": [{"name": "confluence-users"}]},
                            "user": {"results": [{"username": "jdoe"}]},
                        },
                    },
                    {"operation": {"operation": "administer", "targetType": "space"}},
                ]
            },
        )

    cfg = connectors.ConfluenceSettings(
        flavour="datacenter", base_url="https://wiki.acme.local", spaces=["KB"]
    )
    reader = ConfluenceReader(cfg, "pat-1", world.db, transport=httpx.MockTransport(dc))
    who = await reader.space_readers("KB")
    assert who.groups == {"confluence-users"} and who.users == {"jdoe"}


# ---------------------------------------------------------------- databases


def test_only_a_read_only_select_is_accepted() -> None:
    base = dict(
        engine="mysql",
        host="db",
        port=3306,
        database="kb",
        username="ro",
        id_column="id",
        title_column="q",
    )
    connectors.DatabaseSettings(query="SELECT id, q, a FROM faq", **base)  # type: ignore[arg-type]
    for bad in ("UPDATE faq SET a = 1", "SELECT 1; DELETE FROM faq", "CALL wipe()"):
        with pytest.raises(ValidationError, match="SELECT"):
            connectors.DatabaseSettings(query=bad, **base)  # type: ignore[arg-type]


async def test_postgresql_rows_become_documents(world: World, database_url: str) -> None:
    w = world
    url = urlsplit(database_url.replace("+asyncpg", ""))
    table = f"faq_{uuid4().hex[:8]}"
    conn = await asyncpg.connect(database_url.replace("postgresql+asyncpg", "postgresql"))
    try:
        await conn.execute(f"CREATE TABLE {table} (id int, question text, answer text, team text)")
        # The table name is the test's own random name.
        await conn.execute(
            f"INSERT INTO {table} VALUES (1, 'Return window?', '30 days', $1), "  # noqa: S608
            f"(2, 'Gift cards?', 'Not refundable', 'nobody-has-this')",
            w.group.name,
        )
        cfg = connectors.DatabaseSettings(
            engine="postgresql",
            host=url.hostname or "localhost",
            port=url.port or 5432,
            database=url.path.lstrip("/"),
            username=url.username or "",
            query=f"SELECT id, question, answer, team FROM {table} ORDER BY id",  # noqa: S608
            id_column="id",
            title_column="question",
            group_column="team",
        )
        source = await _source(w, "database", cfg, acl=SourceAcl(groups=[w.group.id]))
        reader = DatabaseReader(cfg, url.password or "", w.db)
        assert "returns rows" in await reader.check()
        stats = await sync_listing(w.ingestor(), source, reader.listing())
        assert stats["changed"] == 2
        docs = await _docs(w, source)
        assert docs["rows/1"].acl == {"users": [], "groups": [str(w.group.id)]}
        assert docs["rows/2"].acl == {"users": [], "groups": []}, "unknown group: nobody"
        assert source.config["unmapped"] == ["group value 'nobody-has-this'"]
        assert docs["rows/1"].title == "Return window?.md"
        stats = await sync_listing(
            w.ingestor(), source, DatabaseReader(cfg, url.password or "", w.db).listing()
        )
        assert stats.get("unchanged") == 2
    finally:
        await conn.execute(f"DROP TABLE IF EXISTS {table}")
        await conn.close()


# ---------------------------------------------------------------- file shares


def test_deny_entries_win() -> None:
    aces = [
        ("allow", "S-1-1-0", 0x120089),
        ("allow", "S-1-5-21-1-2-3-500", 0x1F01FF),
        ("deny", "S-1-1-0", 0x1),
    ]
    assert readers_of(aces) == {"S-1-5-21-1-2-3-500"}
    assert readers_of([("allow", "S-1-1-0", 0x00100000)]) == set(), "SYNCHRONIZE is not reading"


SAMBA = "dperson/samba@sha256:66088b78a19810dd1457a8f39340e95e663c728083efa5fe7dc0d40b2478e869"


@pytest.fixture(scope="module")
def samba() -> Iterator[tuple[str, int]]:
    from testcontainers.core.container import DockerContainer  # noqa: PLC0415

    container = (
        DockerContainer(SAMBA)
        .with_command(["-u", "vey;veypass", "-s", "docs;/share;yes;no;no;vey"])
        .with_exposed_ports(445)
    )
    with container:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            code, _ = container.exec("smbclient -L localhost -N")
            if code == 0:
                break
            time.sleep(1)
        container.exec(
            [
                "sh",
                "-c",
                "mkdir -p /share/policies && printf '# Leave\\n30 days.' > "
                "/share/policies/leave.md && echo x > /share/top.txt && chown -R vey /share",
            ]
        )
        yield container.get_container_host_ip(), int(container.get_exposed_port(445))


async def test_file_share_listing_permissions_and_download(
    world: World, samba: tuple[str, int]
) -> None:
    w = world
    host, port = samba
    cfg = connectors.SmbSettings(
        server=host,
        port=port,
        share="docs",
        username="vey",
        include_paths=["policies"],
        sid_map={"S-1-1-0": w.group.id},
    )
    source = await _source(w, "smb", cfg)
    reader = SmbReader(cfg, "veypass", max_bytes=1_000_000)
    try:
        assert "readable" in await reader.check()
        stats = await sync_listing(w.ingestor(), source, reader.listing())
    finally:
        await reader.close()
    assert stats["changed"] == 1, "only the chosen folder"
    doc = (await _docs(w, source))["policies/leave.md"]
    assert doc.acl == {"users": [], "groups": [str(w.group.id)]}, "Everyone maps to the group"
    assert w.objects.data[doc.object_key or ""] == b"# Leave\n30 days."
    assert any(u.startswith("SID S-1-5-21-") for u in source.config["unmapped"])
