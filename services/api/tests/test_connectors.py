"""S3 and website sources: readers and folder rules, the crawl (hosts, paths, robots.txt,
depth), sync of changed and removed files (only after a complete listing), and the S3
reader against a real S3-compatible store (SeaweedFS in a container)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from pydantic import SecretStr, ValidationError
from veyntora_api.db.models.knowledge import DataSource, Document, DocumentStatus
from veyntora_api.knowledge import connectors
from veyntora_api.knowledge.service import KnowledgeError, SourceAcl
from veyntora_workers.connectors.listing import sync_listing
from veyntora_workers.connectors.website import WebsiteReader, links_of

from tests.test_ingestion import CTX, World
from tests.test_sharepoint import Writer

SITE = "https://intranet.example"


def _site(pages: dict[str, tuple[str, str]], robots: str = "") -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        page = pages.get(str(req.url))
        if page is None:
            return httpx.Response(404)
        mime, body = page
        return httpx.Response(200, headers={"content-type": f"{mime}; charset=utf-8"}, text=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


PAGES = {
    f"{SITE}/handbook/": (
        "text/html",
        '<h1>Handbook</h1><a href="leave.html">Leave</a> <a href="/handbook/secret/">x</a>'
        ' <a href="https://elsewhere.example/">out</a> <a href="/blog/">blog</a>'
        ' <a href="travel.md">Travel</a>',
    ),
    f"{SITE}/handbook/leave.html": ("text/html", "<p>30 days of leave.</p>"),
    f"{SITE}/handbook/travel.md": ("text/markdown", "# Travel\nBook trains."),
    f"{SITE}/handbook/secret/": ("text/html", "<p>robots says no</p>"),
    f"{SITE}/blog/": ("text/html", "<p>not under the handbook</p>"),
}


async def _website(w: World, **settings: Any) -> DataSource:
    return await connectors.create_connected_source(
        w.db,
        CTX,
        Writer(),  # type: ignore[arg-type]
        connectors.ConnectedSourceInput(
            name=f"site-{uuid4().hex[:6]}",
            type="website",
            website=connectors.WebsiteSettings(
                start_urls=[f"{SITE}/handbook/"], include_paths=["/handbook"], **settings
            ),
            acl=SourceAcl(groups=[w.group.id]),
            folders=[connectors.FolderReaders(path="/handbook/travel.md", groups=[w.group.id])],
        ),
        w.user.id,
    )


def test_links_and_readers() -> None:
    links, nofollow = links_of('<a href="a.html#top">a</a><a href="mailto:x@y">m</a>', SITE + "/")
    assert links == [f"{SITE}/a.html"] and not nofollow
    assert links_of('<meta name="robots" content="noindex, nofollow">', SITE)[1]

    g1, g2, g3 = uuid4(), uuid4(), uuid4()
    source = DataSource(
        config={
            "acl": {"groups": [str(g1)], "users": []},
            "folders": [
                {"path": "policies", "groups": [str(g2)]},
                {"path": "/policies/hr/", "groups": [str(g3)]},
            ],
        }
    )
    assert connectors.readers_for(source, "policies/hr/leave.pdf")["groups"] == [str(g3)]
    assert connectors.readers_for(source, "policies/it.pdf")["groups"] == [str(g2)]
    assert connectors.readers_for(source, "policiesX/it.pdf")["groups"] == [str(g1)]
    assert connectors.readers_for(source, "other.pdf")["groups"] == [str(g1)]


def test_inputs_are_checked() -> None:
    with pytest.raises(ValidationError, match="secret access key"):
        connectors.ConnectedSourceInput(
            name="b",
            type="s3",
            s3=connectors.S3Settings(bucket="docs", access_key_id="AKIA123"),
            acl=SourceAcl(groups=[uuid4()]),
        )
    with pytest.raises(ValidationError, match="http"):
        connectors.WebsiteSettings(start_urls=["ftp://x.example/"])


async def test_crawl_follows_hosts_paths_and_robots(world: World) -> None:
    w = world
    source = await _website(w)
    reader = WebsiteReader(
        connectors.WebsiteSettings(start_urls=[f"{SITE}/handbook/"], include_paths=["/handbook"]),
        max_bytes=1_000_000,
        http=_site(PAGES, robots="User-agent: *\nDisallow: /handbook/secret/\n"),
    )
    ing = w.ingestor()
    stats = await sync_listing(ing, source, reader.listing())
    assert stats["changed"] == 3 and "incomplete" not in stats
    docs = {
        d.path: d
        for d in (
            await w.db.execute(sa.select(Document).where(Document.source_id == source.id))
        ).scalars()
    }
    assert set(docs) == {"/handbook/", "/handbook/leave.html", "/handbook/travel.md"}
    assert docs["/handbook/"].title == "handbook.html"
    assert docs["/handbook/leave.html"].acl == {"users": [], "groups": [str(w.group.id)]}

    # Unchanged pages are not stored again; a page that disappears is removed.
    pages = {k: v for k, v in PAGES.items() if not k.endswith("leave.html")}
    reader = WebsiteReader(
        connectors.WebsiteSettings(start_urls=[f"{SITE}/handbook/"], include_paths=["/handbook"]),
        max_bytes=1_000_000,
        http=_site(pages),
    )
    stats = await sync_listing(ing, source, reader.listing())
    assert stats.get("unchanged") == 2 and stats.get("deleted") == 1
    await w.db.refresh(docs["/handbook/leave.html"])
    assert docs["/handbook/leave.html"].status is DocumentStatus.DELETED


async def test_a_crawl_cut_short_removes_nothing(world: World) -> None:
    w = world
    source = await _website(w)
    ing = w.ingestor()
    full = WebsiteReader(
        connectors.WebsiteSettings(start_urls=[f"{SITE}/handbook/"]),
        max_bytes=1_000_000,
        http=_site(PAGES),
    )
    await sync_listing(ing, source, full.listing())
    short = WebsiteReader(
        connectors.WebsiteSettings(start_urls=[f"{SITE}/handbook/"], max_pages=1),
        max_bytes=1_000_000,
        http=_site(PAGES),
    )
    stats = await sync_listing(ing, source, short.listing())
    assert stats.get("incomplete") == 1 and "deleted" not in stats


async def test_s3_needs_its_secret_and_keeps_it_write_only(world: World) -> None:
    w = world
    writer = Writer()
    source = await connectors.create_connected_source(
        w.db,
        CTX,
        writer,  # type: ignore[arg-type]
        connectors.ConnectedSourceInput(
            name=f"bucket-{uuid4().hex[:6]}",
            type="s3",
            s3=connectors.S3Settings(
                endpoint_url="http://s3.internal:8333", bucket="policies", access_key_id="AK123"
            ),
            acl=SourceAcl(groups=[w.group.id]),
            secret=SecretStr("s3-secret-key-WXYZ"),
        ),
        w.user.id,
    )
    assert source.secret_last4 == "WXYZ" and "s3-secret-key-WXYZ" not in str(source.config)
    with pytest.raises(KnowledgeError, match="unknown groups"):
        await connectors.update_connected(
            w.db,
            CTX,
            source,
            connectors.ConnectedUpdate(
                folders=[connectors.FolderReaders(path="hr/", groups=[uuid4()])]
            ),
            expected_version=None,
            triggered_by=None,
        )


@pytest.fixture
async def world(db: Any) -> World:
    return await World(db).setup()


# ---------------------------------------------------------------- real S3


async def test_s3_reader_against_a_real_store(s3_endpoint: str) -> None:
    import aioboto3  # noqa: PLC0415
    from veyntora_workers.connectors.s3 import S3Reader  # noqa: PLC0415

    session = aioboto3.Session()
    creds = {"aws_access_key_id": "any", "aws_secret_access_key": "any"}
    async with session.client(
        "s3", endpoint_url=s3_endpoint, region_name="us-east-1", **creds
    ) as s3:
        await s3.create_bucket(Bucket="policies")
        await s3.put_object(Bucket="policies", Key="hr/leave.md", Body=b"# Leave\n30 days.")
        await s3.put_object(Bucket="policies", Key="it/vpn.md", Body=b"# VPN")
        await s3.put_object(Bucket="policies", Key="hr/", Body=b"")
    reader = S3Reader(
        connectors.S3Settings(
            endpoint_url=s3_endpoint, bucket="policies", prefixes=["hr/"], access_key_id="any"
        ),
        "any",
    )
    assert "readable" in await reader.check()
    entries = [e async for e in reader.entries()]
    assert [e.path for e in entries] == ["hr/leave.md"] and reader.listed_all
    assert entries[0].version and isinstance(entries[0].modified, datetime)
    assert await reader.download(entries[0]) == b"# Leave\n30 days."
