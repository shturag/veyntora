"""How each source reads its documents, and which files (ADR 0040)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from veyntora_api.chatbots import service as bots
from veyntora_api.db.models.knowledge import DataSource, DocumentStatus, IngestJobKind, SourceType
from veyntora_api.knowledge import connectors, reading
from veyntora_api.knowledge import service as knowledge
from veyntora_api.knowledge.profiles import index_plan
from veyntora_api.rag.pipeline import load_context
from veyntora_spec.extraction import ExtractionMethod, ExtractionSpec, FileFilters, SourceReading
from veyntora_workers import textlayer
from veyntora_workers.connectors.listing import sync_listing
from veyntora_workers.connectors.website import WebsiteReader
from veyntora_workers.titles import best_title

from tests.test_connectors import PAGES, SITE, _site, _website
from tests.test_fast_rag import Authz
from tests.test_ingestion import CTX, FakeParser, World, _bot_with_source


def _pdf(*pages: str) -> bytes:
    """A small PDF with one line of text per page ("" for a page without text, like a scan)."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


@pytest.fixture
async def world(db: Any) -> World:
    return await World(db).setup()


TEXT_PDF = _pdf(
    "Refunds for digital products are possible within one year.",
    "Physical products can be returned within thirty days.",
)
SCANNED_PDF = _pdf("", "")


def test_filters_choose_the_files() -> None:
    f = FileFilters(file_types=[".PDF", "docx"], include=["/policies/*"], exclude=["*draft*"])
    assert f.file_types == ["docx", "pdf"]
    limit = 10 * 1024 * 1024
    assert reading.skipped(f, "/policies/leave.pdf", 100, limit) is None
    assert reading.skipped(f, "/policies/leave.txt", 100, limit) == "filtered"
    assert reading.skipped(f, "/other/leave.pdf", 100, limit) == "filtered"
    assert reading.skipped(f, "/policies/leave-draft.pdf", 100, limit) == "filtered"
    small = FileFilters(max_file_mb=1)
    assert reading.size_limit(small, limit) == 1024 * 1024
    assert reading.skipped(small, "/a.pdf", 2 * 1024 * 1024, limit) == "too_large"
    # Web pages are typed by their content ("index.html"), not their address ("/handbook/").
    html = FileFilters(file_types=["html"])
    assert reading.skipped(html, "/handbook/", None, limit, name="handbook.html") is None
    assert reading.skipped(html, "/handbook/a.pdf", None, limit, name="a.pdf") == "filtered"
    # A pattern without a slash matches the name anywhere.
    assert reading.skipped(FileFilters(exclude=["*.tmp"]), "/x/y/z.tmp", None, limit)
    with pytest.raises(ValueError, match="vision model"):
        ExtractionSpec(method=ExtractionMethod.VISION)


def test_text_layer() -> None:
    title, texts = textlayer.pages(TEXT_PDF)
    assert texts[0].startswith("Refunds for digital products") and textlayer.has_text_layer(texts)
    assert not textlayer.has_text_layer(textlayer.pages(SCANNED_PDF)[1])
    doc = textlayer.parsed(title, texts, max_tokens=500)
    assert [s.pages for s in doc.sections] == [(1,), (2,)] and doc.page_count == 2
    long = textlayer.parsed("", ["word " * 2000], max_tokens=100)
    assert len(long.sections) > 5
    with pytest.raises(textlayer.TextLayerError):
        textlayer.pages(b"not a pdf")


async def _set(world: World, source: Any, **extraction: Any) -> None:
    ex = ExtractionSpec(parser_instance_id=world.parser, **extraction)
    await reading.set_reading(
        world.db,
        CTX,
        source,
        SourceReading(extraction=ex),
        expected_version=None,
        triggered_by=None,
    )


async def _upload_pdf(world: World, source: Any, content: bytes) -> Any:
    doc, _ = await knowledge.add_upload(
        world.db,
        CTX,
        world.objects,  # type: ignore[arg-type]
        source,
        filename="policy.pdf",
        content=content,
        uploader_id=world.user.id,
        max_bytes=100_000,
    )
    return doc


async def test_each_source_reads_its_documents_its_own_way(world: World) -> None:
    bot, source = await _bot_with_source(world)
    before = (await index_plan(world.db, source.id))[0][0]

    await _set(world, source, method=ExtractionMethod.TEXT)
    [profile] = (await index_plan(world.db, source.id))[0]
    assert profile.reading == "text" and profile.key != before.key
    # Saving a new reading syncs the source, so its documents are indexed the new way.
    assert await world.jobs(IngestJobKind.SYNC)

    calls = FakeParser.calls
    doc = await _upload_pdf(world, source, TEXT_PDF)
    stats = await world.ingestor().index_document(doc, force=False)
    assert stats["indexed"] == 1 and doc.status is DocumentStatus.INDEXED
    assert FakeParser.calls == calls, "the text layer is read without the parser"
    points = world.vectors.of(doc.id)
    assert {p.payload["profile"] for p in points} == {profile.key}
    assert any("thirty days" in p.payload["text"] for p in points)

    # Search looks under the key the source was indexed with.
    await bots.set_governance(
        world.db,
        CTX,
        bot,
        bots.GovernanceInput(
            allowed_external_instance_ids=[world.llm], mask_pii_before_external=False
        ),
    )
    await bots.publish(world.db, CTX, bot, None)
    ctx = await load_context(world.db, Authz(), world.user.keycloak_sub, bot.id)
    assert ctx.profile_keys == (profile.key,)


async def test_auto_sends_scans_to_the_parser(world: World) -> None:
    _, source = await _bot_with_source(world)
    await _set(world, source)
    calls = FakeParser.calls
    text = await _upload_pdf(world, source, TEXT_PDF)
    await world.ingestor().index_document(text, force=False)
    assert FakeParser.calls == calls
    scan = await _upload_pdf(world, source, SCANNED_PDF + b"\n% another file")
    await world.ingestor().index_document(scan, force=False)
    assert FakeParser.calls == calls + 1, "a PDF without text goes to the parser (OCR)"


async def test_reading_needs_real_providers(world: World) -> None:
    _, source = await _bot_with_source(world)
    with pytest.raises(knowledge.KnowledgeError, match="parser"):
        await reading.check_reading(world.db, SourceReading(extraction=ExtractionSpec()))
    wrong = ExtractionSpec(parser_instance_id=world.embed)
    with pytest.raises(knowledge.KnowledgeError, match="parser provider"):
        await reading.check_reading(world.db, SourceReading(extraction=wrong))
    with pytest.raises(knowledge.KnowledgeError, match="cannot be read"):
        await reading.check_reading(
            world.db, SourceReading(filters=FileFilters(file_types=["exe"]))
        )
    assert source.config.get("reading") is None, "nothing was saved"


async def test_filters_skip_files_and_remove_them(world: World) -> None:
    source = await _website(world)
    pages = {**PAGES}

    async def sync() -> dict[str, Any]:
        reader = WebsiteReader(
            connectors.settings_of(source),  # type: ignore[arg-type]
            max_bytes=100_000,
            http=_site(pages, robots="User-agent: *\nDisallow: /handbook/secret/"),
        )
        return await sync_listing(world.ingestor(), source, reader.listing())

    first = await sync()
    assert first.get("changed") == 3
    await reading.set_reading(
        world.db,
        CTX,
        source,
        SourceReading(filters=FileFilters(file_types=["html"])),
        expected_version=None,
        triggered_by=None,
    )
    second = await sync()
    assert second.get("filtered") == 1 and second.get("deleted") == 1


async def test_sitemaps_find_unlinked_pages() -> None:
    sitemap = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{SITE}/handbook/hidden.html</loc></url>"
        "<url><loc>https://elsewhere.example/x</loc></url></urlset>"
    )
    pages = {
        **PAGES,
        f"{SITE}/handbook/hidden.html": ("text/html", "<p>no link leads here</p>"),
        f"{SITE}/maps/site.xml": ("application/xml", sitemap),
    }
    robots = f"User-agent: *\nDisallow: /handbook/secret/\nSitemap: {SITE}/maps/site.xml"

    async def crawl(**settings: Any) -> set[str]:
        cfg = connectors.WebsiteSettings(
            start_urls=[f"{SITE}/handbook/"], include_paths=["/handbook"], **settings
        )
        reader = WebsiteReader(cfg, max_bytes=100_000, http=_site(pages, robots=robots))
        return {e.url or "" async for e in reader.entries()}

    assert f"{SITE}/handbook/hidden.html" not in await crawl()
    found = await crawl(use_sitemap=True, delay_seconds=0.01)
    assert f"{SITE}/handbook/hidden.html" in found
    assert not any("elsewhere" in u for u in found), "other hosts stay out"

    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><urlset/>'
    pages[f"{SITE}/maps/site.xml"] = ("application/xml", evil)
    reader = WebsiteReader(
        connectors.WebsiteSettings(start_urls=[f"{SITE}/handbook/"], use_sitemap=True),
        max_bytes=100_000,
        http=_site(pages, robots=robots),
    )
    assert await reader.sitemap_urls() == [], "sitemaps with a DTD are refused"


def test_website_settings_keep_old_sources_valid() -> None:
    # A website source saved before sitemaps and delays existed.
    saved = DataSource(
        type=SourceType.WEBSITE,
        config={"start_urls": [f"{SITE}/"], "include_paths": [], "max_pages": 9, "max_depth": 2},
    )
    old = connectors.settings_of(saved)
    assert isinstance(old, connectors.WebsiteSettings) and old.max_pages == 9
    assert old.use_sitemap is False and old.delay_seconds == 0.0


async def test_chunks_no_chatbot_needs_are_removed_after_a_grace_period(world: World) -> None:
    _, source = await _bot_with_source(world)
    doc = await _upload_pdf(world, source, TEXT_PDF)
    ing = world.ingestor()
    await ing.index_document(doc, force=False)
    old = {p.payload["profile"] for p in world.vectors.of(doc.id)}
    await _set(world, source, method=ExtractionMethod.TEXT)
    await ing.index_document(doc, force=False)
    [new] = [p.key for p in (await index_plan(world.db, source.id))[0]]
    both = {p.payload["profile"] for p in world.vectors.of(doc.id)}
    assert both == old | {new}

    assert await ing.prune_unused() == 0, "kept within the grace period (rollbacks)"
    assert await ing.prune_unused(grace=timedelta(0)) == 1
    assert {p.payload["profile"] for p in world.vectors.of(doc.id)} == {new}


def test_titles_that_are_not_titles_are_replaced() -> None:
    path = "Library/Agentic_AI/22_Reflexion_Language_Agents_with_Verbal_Reinforcement_Learning.pdf"
    named = "Reflexion Language Agents with Verbal Reinforcement Learning"
    assert best_title("Noah Shinn", path, "x.pdf") == named
    assert best_title("Abstract", path, "x.pdf") == named
    authors = "Timo Schick Jane Dwivedi-Yu Roberto Dessì† Roberta Raileanu"
    assert best_title(authors, path, "x.pdf") == named
    # Real titles stay, short ones too.
    assert best_title("Attention Is All You Need", path, "x.pdf") == "Attention Is All You Need"
    assert best_title("Deep Residual Learning", "a/resnet.pdf", "resnet.pdf") == (
        "Deep Residual Learning"
    )
    # A name with nothing better to replace it keeps the current title.
    assert best_title("Abstract", "a/notes.pdf", "notes.pdf") == "notes.pdf"
