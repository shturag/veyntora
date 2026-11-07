"""Document management systems through CMIS 1.1 (browser binding): Alfresco, and others
that publish it (OpenText, d.velop, enaio, Nuxeo, …), with their permissions.

- Documents of the chosen folders are listed folder by folder (`cmisselector=children`);
  the change token (else the modification time) tells changed documents apart. The
  version series id keeps a document the same across its versions.
- Who may read (fail closed): the document's ACL; principals with cmis:read, cmis:write
  or cmis:all. Groups and the "anyone" principal map through the group map; users whose
  id is an e-mail address map to the Veyntora user with that address. Whatever cannot be
  mapped is dropped and listed on the source.

Not tested against a live repository yet; the responses follow the CMIS 1.1 standard.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.knowledge.connectors import CmisSettings

from veyntora_workers.connectors.listing import Entry, Listing
from veyntora_workers.connectors.principals import PrincipalMap

READ = {"cmis:read", "cmis:write", "cmis:all"}
_PAGE = 100


def readers_of(acl: dict[str, Any]) -> set[str]:
    """Principal ids allowed to read (CMIS has no deny entries)."""
    return {
        str((ace.get("principal") or {}).get("principalId"))
        for ace in acl.get("aces") or []
        if READ & set(ace.get("permissions") or [])
    }


class CmisReader:
    def __init__(
        self,
        cfg: CmisSettings,
        password: str,
        db: AsyncSession,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cfg = cfg
        self.http = httpx.AsyncClient(
            timeout=60, auth=httpx.BasicAuth(cfg.username, password), transport=transport
        )
        self.map = PrincipalMap(db, cfg.group_map)
        self.listed_all = False
        self._root = ""
        self._name = ""
        # Version series id -> the listed (latest) version's object id, for the download.
        self._objects: dict[str, str] = {}

    async def close(self) -> None:
        await self.http.aclose()

    async def _json(self, url: str, **params: Any) -> dict[str, Any]:
        res = await self.http.get(url, params=params or None)
        res.raise_for_status()
        data: dict[str, Any] = res.json()
        return data

    async def _repository(self) -> None:
        if self._root:
            return
        repos = await self._json(self.cfg.browser_url.rstrip("/"))
        if not repos:
            raise RuntimeError("the CMIS address lists no repository")
        info = repos.get(self.cfg.repository_id or "") or next(iter(repos.values()))
        if self.cfg.repository_id and info.get("repositoryId") != self.cfg.repository_id:
            raise RuntimeError(f"repository {self.cfg.repository_id} not found")
        self._root = str(info["rootFolderUrl"]).rstrip("/")
        self._name = str(info.get("repositoryName") or info.get("repositoryId"))

    async def _folder_id(self, path: str) -> str:
        obj = await self._json(
            f"{self._root}/{quote(path.strip('/'))}", cmisselector="object", succinct="true"
        )
        return str(obj["succinctProperties"]["cmis:objectId"])

    async def check(self) -> str:
        await self._repository()
        await self._folder_id(self.cfg.folders[0])
        return f"Repository {self._name} is readable; folder {self.cfg.folders[0]} found."

    async def _children(self, folder_id: str) -> AsyncIterator[dict[str, Any]]:
        skip = 0
        while True:
            page = await self._json(
                self._root,
                objectId=folder_id,
                cmisselector="children",
                succinct="true",
                maxItems=_PAGE,
                skipCount=skip,
            )
            objects = page.get("objects") or []
            for item in objects:
                yield (item.get("object") or {}).get("succinctProperties") or {}
            if not page.get("hasMoreItems") or not objects:
                return
            skip += len(objects)

    async def _acl(self, object_id: str) -> dict[str, list[str]]:
        acl = await self._json(
            self._root, objectId=object_id, cmisselector="acl", onlyBasicPermissions="true"
        )
        emails: set[str] = set()
        groups: set[UUID] = set()
        unmapped: set[str] = set()
        for principal in readers_of(acl):
            if (mapped := self.map.group(principal)) is not None:
                groups.add(mapped)
            elif "@" in principal:
                emails.add(principal)
            else:
                unmapped.add(f"principal {principal}")
        return await self.map.acl(emails, groups, unmapped)

    async def entries(self) -> AsyncIterator[Entry]:
        await self._repository()
        count = 0
        for top in self.cfg.folders:
            todo = [("/" + top.strip("/"), await self._folder_id(top))]
            while todo:
                path, folder_id = todo.pop()
                async for props in self._children(folder_id):
                    name = str(props.get("cmis:name") or "")
                    kind = str(props.get("cmis:baseTypeId") or "")
                    if kind == "cmis:folder":
                        todo.append((f"{path}/{name}", str(props["cmis:objectId"])))
                        continue
                    if kind != "cmis:document" or not props.get("cmis:contentStreamLength"):
                        continue
                    count += 1
                    if count > self.cfg.max_documents:
                        return  # not complete: nothing is removed
                    object_id = str(props["cmis:objectId"])
                    series = str(props.get("cmis:versionSeriesId") or object_id)
                    self._objects[series] = object_id
                    when = props.get("cmis:lastModificationDate")
                    modified = (
                        datetime.fromtimestamp(int(when) / 1000, UTC)
                        if isinstance(when, int | float)
                        else None
                    )
                    yield Entry(
                        external_id=series,
                        path=f"{path}/{name}".lstrip("/"),
                        name=name,
                        url=None,
                        version=str(props.get("cmis:changeToken") or when or "") or None,
                        size=int(props["cmis:contentStreamLength"]),
                        modified=modified,
                        acl=await self._acl(object_id),
                    )
        self.listed_all = True

    async def download(self, entry: Entry) -> bytes:
        res = await self.http.get(
            self._root,
            params={
                "objectId": self._objects.get(entry.external_id, entry.external_id),
                "cmisselector": "content",
            },
        )
        res.raise_for_status()
        return res.content

    def listing(self) -> Listing:
        return Listing(
            entries=self.entries(),
            download=self.download,
            complete=lambda: self.listed_all,
            unmapped=lambda: self.map.unmapped,
        )
