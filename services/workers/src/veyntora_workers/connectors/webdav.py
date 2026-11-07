"""Nextcloud, ownCloud and other WebDAV servers: files of the chosen folders.

- Folders are listed with PROPFIND (depth 1, folder by folder: Nextcloud refuses
  "infinity"); the ETag tells changed files apart, so later syncs download only those.
- Nextcloud and ownCloud: files are under /remote.php/dav/files/<user>; sign in with an
  app password (Settings → Security), which can be revoked on its own. Links open the
  file in Nextcloud (/index.php/f/<file id>).
- Who may read: the source's readers and folder rules (Nextcloud shares are not mapped).

XML: answers with a DTD are refused (WebDAV never sends one), so no entity can be
declared, expanded or fetched; the standard library parser reads the rest.
"""

from __future__ import annotations

import posixpath
from collections.abc import AsyncIterator
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree as ET

import httpx
from veyntora_api.knowledge.connectors import WebdavSettings

from veyntora_workers.connectors.listing import Entry, Listing

_MAX_FILES = 50_000
_NS = {"d": "DAV:", "oc": "http://owncloud.org/ns"}
_PROPFIND = (
    b'<?xml version="1.0"?>'
    b'<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:prop>'
    b"<d:resourcetype/><d:getetag/><d:getlastmodified/><d:getcontentlength/><oc:fileid/>"
    b"</d:prop></d:propfind>"
)


class WebdavReader:
    def __init__(
        self,
        cfg: WebdavSettings,
        password: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cfg = cfg
        base = cfg.base_url.rstrip("/")
        self.base = base
        self.root = (
            f"{base}/remote.php/dav/files/{quote(cfg.username)}"
            if cfg.flavour == "nextcloud"
            else base
        )
        self._root_path = unquote(urlsplit(self.root).path).rstrip("/")
        self.http = httpx.AsyncClient(
            timeout=60, auth=httpx.BasicAuth(cfg.username, password), transport=transport
        )
        self.listed_all = False

    async def close(self) -> None:
        await self.http.aclose()

    def _url(self, rel: str) -> str:
        return f"{self.root}/{quote(rel)}" if rel else f"{self.root}/"

    async def _list(self, rel: str, depth: str = "1") -> list[tuple[str, ET.Element]]:
        """(path relative to the root, its response element) for a folder and its children."""
        res = await self.http.request(
            "PROPFIND",
            self._url(rel).rstrip("/") + "/",  # a folder
            content=_PROPFIND,
            headers={"Depth": depth, "Content-Type": "application/xml"},
        )
        res.raise_for_status()
        if b"<!DOCTYPE" in res.content or b"<!ENTITY" in res.content:
            raise RuntimeError("the server answered with a DTD; refused")
        out = []
        root = ET.fromstring(res.content)  # noqa: S314 - no DTD (checked above)
        for item in root.findall("d:response", _NS):
            href = unquote(urlsplit(item.findtext("d:href", "", _NS)).path)
            out.append((href.removeprefix(self._root_path).strip("/"), item))
        return out

    async def check(self) -> str:
        rel = (self.cfg.include_paths or [""])[0]
        items = await self._list(rel)
        return f"Folder /{rel} is readable; {max(len(items) - 1, 0)} entries in it."

    def _entry(self, rel: str, item: ET.Element) -> Entry | None:
        prop = item.find("d:propstat/d:prop", _NS)
        if prop is None or prop.find("d:resourcetype/d:collection", _NS) is not None:
            return None
        size = prop.findtext("d:getcontentlength", "", _NS)
        when = prop.findtext("d:getlastmodified", "", _NS)
        fileid = prop.findtext("oc:fileid", "", _NS)
        return Entry(
            external_id=rel,
            path=rel,
            name=posixpath.basename(rel),
            url=(
                f"{self.base}/index.php/f/{fileid}"
                if self.cfg.flavour == "nextcloud" and fileid
                else self._url(rel)
            ),
            version=(prop.findtext("d:getetag", "", _NS) or "").strip('"') or None,
            size=int(size) if size.isdigit() else None,
            modified=_date(when),
        )

    async def entries(self) -> AsyncIterator[Entry]:
        todo = list(self.cfg.include_paths or [""])
        seen: set[str] = set()
        files = 0
        while todo:
            folder = todo.pop()
            if folder in seen:
                continue
            seen.add(folder)
            for rel, item in await self._list(folder):
                if rel == folder:
                    continue
                if item.find("d:propstat/d:prop/d:resourcetype/d:collection", _NS) is not None:
                    todo.append(rel)
                elif (entry := self._entry(rel, item)) is not None:
                    files += 1
                    if files > _MAX_FILES:
                        return  # not complete: nothing is removed
                    yield entry
        self.listed_all = True

    async def download(self, entry: Entry) -> bytes:
        res = await self.http.get(self._url(entry.external_id))
        res.raise_for_status()
        return res.content

    def listing(self) -> Listing:
        return Listing(
            entries=self.entries(), download=self.download, complete=lambda: self.listed_all
        )


def _date(value: str) -> datetime | None:
    try:
        return parsedate_to_datetime(value) if value else None
    except (TypeError, ValueError):
        return None
