"""Websites: crawl from the start pages, breadth first.

- Only hosts of the start pages are followed (redirects elsewhere are skipped), only paths
  below `include_paths` when set, up to `max_depth` links deep and `max_pages` pages.
- robots.txt is respected for our user agent.
- HTML pages are stored as UTF-8 HTML and parsed like uploads; linked files of supported
  types (PDF, Office, text) are read too.
- The page's content hash tells changed pages apart (websites rarely send stable ETags).
- With `use_sitemap`, the pages the site's sitemaps list are crawled too (ADR 0040), and
  `delay_seconds` spaces out requests.
"""

from __future__ import annotations

import asyncio
import posixpath
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import AsyncIterator
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from veyntora_api.knowledge.connectors import WebsiteSettings
from veyntora_api.knowledge.service import UPLOAD_TYPES

from veyntora_workers.connectors.listing import Entry, Listing

USER_AGENT = "VeyntoraBot/1.0 (+knowledge sync)"
# Sitemaps read at most (an index may list many), and pages taken from them.
_MAX_SITEMAPS = 20
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_BY_MIME = {mime: ext for ext, mime in reversed(list(UPLOAD_TYPES.items()))}


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.nofollow = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "a" and a.get("href") and "nofollow" not in (a.get("rel") or ""):
            self.links.append(str(a["href"]))
        if tag == "meta" and (a.get("name") or "").lower() == "robots":
            self.nofollow = "nofollow" in (a.get("content") or "").lower()


def links_of(html: str, base: str) -> tuple[list[str], bool]:
    parser = _Links()
    parser.feed(html)
    out = []
    for href in parser.links:
        url = urldefrag(urljoin(base, href.strip()))[0]
        if urlsplit(url).scheme in {"http", "https"}:
            out.append(url)
    return out, parser.nofollow


def _name(url: str, mime: str) -> str:
    """A file name whose extension matches the content type."""
    path = urlsplit(url).path
    base = posixpath.basename(path.rstrip("/")) or "index"
    ext = _BY_MIME.get(mime, "")
    stem, current = posixpath.splitext(base)
    if current.lower() in UPLOAD_TYPES and UPLOAD_TYPES[current.lower()] == mime:
        return base
    return f"{stem or base}{ext}"


class WebsiteReader:
    def __init__(
        self,
        cfg: WebsiteSettings,
        *,
        max_bytes: int,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.cfg = cfg
        self.max_bytes = max_bytes
        self.http = http or httpx.AsyncClient(
            timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
        self.hosts = {urlsplit(u).netloc.lower() for u in cfg.start_urls}
        self._robots: dict[str, RobotFileParser] = {}
        self.complete_crawl = False
        self.errors = 0
        self._requests = 0

    async def close(self) -> None:
        await self.http.aclose()

    def _wanted(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.netloc.lower() not in self.hosts:
            return False
        if not self.cfg.include_paths:
            return True
        path = parts.path or "/"
        return any(path.startswith("/" + p.strip("/")) for p in self.cfg.include_paths)

    async def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        robots = self._robots.get(parts.netloc)
        if robots is None:
            robots = RobotFileParser()
            try:
                res = await self.http.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
                robots.parse(res.text.splitlines() if res.status_code == 200 else [])
            except httpx.HTTPError:
                robots.parse([])
            self._robots[parts.netloc] = robots
        return robots.can_fetch(USER_AGENT, url)

    async def _pause(self) -> None:
        if self.cfg.delay_seconds and self._requests:
            await asyncio.sleep(self.cfg.delay_seconds)
        self._requests += 1

    async def sitemap_urls(self) -> list[str]:
        """Pages the sitemaps of the start pages' hosts list (sitemap indexes are followed)."""
        todo: deque[str] = deque()
        for host in sorted({urlsplit(u)[:2] for u in self.cfg.start_urls}):
            base = f"{host[0]}://{host[1]}"
            await self._allowed(base + "/")  # reads robots.txt, which may name sitemaps
            named = self._robots[host[1]].site_maps() or []
            todo.extend(named or [base + "/sitemap.xml"])
        pages: list[str] = []
        read = 0
        while todo and read < _MAX_SITEMAPS and len(pages) < self.cfg.max_pages:
            url = todo.popleft()
            read += 1
            if urlsplit(url).netloc.lower() not in self.hosts:
                continue
            await self._pause()
            try:
                res = await self.http.get(url)
            except httpx.HTTPError:
                continue
            body = res.content
            if res.status_code != 200 or len(body) > self.max_bytes:
                continue
            if b"<!DOCTYPE" in body or b"<!ENTITY" in body:
                continue  # no DTDs, so no entity expansion
            try:
                root = ET.fromstring(body)  # noqa: S314 - no DTD (checked above)
            except ET.ParseError:
                continue
            locs = [(el.text or "").strip() for el in root.iter(f"{_SITEMAP_NS}loc")]
            if root.tag == f"{_SITEMAP_NS}sitemapindex":
                todo.extend(locs)
            else:
                pages += [u for u in locs if u and self._wanted(u)]
        return pages[: self.cfg.max_pages]

    async def _get(self, url: str) -> tuple[str, str, bytes] | None:
        """(final url, mime, body) or None when skipped."""
        await self._pause()
        async with self.http.stream("GET", url) as res:
            final = str(res.url)
            if res.status_code != 200 or not self._wanted(final):
                if res.status_code >= 500:
                    self.errors += 1
                return None
            mime = res.headers.get("content-type", "").split(";")[0].strip().lower()
            if mime not in _BY_MIME:
                return None
            body = b""
            async for chunk in res.aiter_bytes():
                body += chunk
                if len(body) > self.max_bytes:
                    return None
            if mime == "text/html":
                # Stored as UTF-8 whatever the page's charset.
                body = body.decode(res.encoding or "utf-8", errors="replace").encode()
        return final, mime, body

    async def check(self) -> str:
        found = 0
        for url in self.cfg.start_urls:
            got = await self._get(url) if await self._allowed(url) else None
            found += got is not None
        if not found:
            raise RuntimeError("no start page could be read (status, type or robots.txt)")
        return f"{found} of {len(self.cfg.start_urls)} start pages are readable."

    async def entries(self) -> AsyncIterator[Entry]:
        starts = list(self.cfg.start_urls)
        if self.cfg.use_sitemap:
            starts += [u for u in await self.sitemap_urls() if u not in starts]
        queue = deque((u, 0) for u in starts)
        seen: set[str] = set(starts)
        read: set[str] = set()
        pages = 0
        while queue:
            if pages >= self.cfg.max_pages:
                return  # cut short: nothing is removed this time
            url, depth = queue.popleft()
            if not self._wanted(url) or not await self._allowed(url):
                continue
            try:
                got = await self._get(url)
            except httpx.HTTPError:
                self.errors += 1
                continue
            if got is None:
                continue
            final, mime, body = got
            if final in read:
                continue  # another address redirected to a page already read
            read.add(final)
            pages += 1
            parts = urlsplit(final)
            yield Entry(
                external_id=final,
                path=parts.path or "/",
                name=_name(final, mime),
                url=final,
                version=None,
                size=len(body),
                modified=None,
                content=body,
            )
            if mime != "text/html" or depth >= self.cfg.max_depth:
                continue
            links, nofollow = links_of(body.decode(errors="replace"), final)
            if nofollow:
                continue
            for link in links:
                if link not in seen and self._wanted(link):
                    seen.add(link)
                    queue.append((link, depth + 1))
        self.complete_crawl = self.errors == 0

    async def _no_download(self, entry: Entry) -> bytes:
        raise RuntimeError(f"{entry.url} was not read during the crawl")

    def listing(self) -> Listing:
        return Listing(
            entries=self.entries(),
            download=self._no_download,
            complete=lambda: self.complete_crawl,
        )
