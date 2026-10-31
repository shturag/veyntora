"""Confluence Cloud and Data Center: pages of the chosen spaces, with their permissions.

- Pages come from the REST API (`/rest/api/content`, storage format), the same on Cloud
  and Data Center. Cloud signs in with an e-mail and API token, Data Center with a
  personal access token.
- Who may read a page (fail closed):
  - the space's read permissions (Cloud: `/api/v2/spaces/{id}/permissions`; Data Center:
    `/rest/api/space/{key}?expand=permissions`);
  - narrowed by the read restrictions of the page and of every ancestor: only users and
    groups that every level lists, and that the space lets read, remain;
  - groups map to Veyntora groups by name (the source's group map), users by e-mail;
    whatever cannot be mapped is dropped and listed on the source.
- The page version number tells changed pages apart.

Not tested against a live Confluence yet; the responses follow the documented shapes.
"""

from __future__ import annotations

import html
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.identity import User
from veyntora_api.knowledge.connectors import ConfluenceSettings

from veyntora_workers.connectors.listing import Entry, Listing

_PAGE = 50
_MAX_PAGES = 5000


@dataclass
class Principals:
    users: set[str] = field(default_factory=set)  # e-mail addresses (lower case) or usernames
    groups: set[str] = field(default_factory=set)  # Confluence group names

    def narrowed(self, other: Principals) -> Principals:
        return Principals(self.users & other.users, self.groups & other.groups)

    def empty(self) -> bool:
        return not self.users and not self.groups


def _restriction(page: dict[str, Any]) -> Principals | None:
    """The page's own read restriction (None: not restricted)."""
    read = ((page.get("restrictions") or {}).get("read") or {}).get("restrictions") or {}
    users = (read.get("user") or {}).get("results") or []
    groups = (read.get("group") or {}).get("results") or []
    if not users and not groups:
        return None
    return Principals(
        {str(u.get("email") or u.get("username") or u.get("accountId")).lower() for u in users},
        {str(g.get("name")) for g in groups if g.get("name")},
    )


class ConfluenceReader:
    def __init__(
        self,
        cfg: ConfluenceSettings,
        token: str,
        db: AsyncSession,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cfg = cfg
        self.db = db
        base = cfg.base_url.rstrip("/")
        auth: httpx.Auth | None = None
        headers = {"Accept": "application/json"}
        if cfg.flavour == "cloud":
            auth = httpx.BasicAuth(cfg.email or "", token)
        else:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.AsyncClient(timeout=30, auth=auth, headers=headers, transport=transport)
        self.base = base
        self.listed_all = False
        self._unmapped: set[str] = set()
        self._emails: dict[str, UUID] | None = None

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        res = await self.http.get(f"{self.base}{path}", params=params or None)
        res.raise_for_status()
        data: dict[str, Any] = res.json()
        return data

    async def check(self) -> str:
        key = self.cfg.spaces[0]
        space = await self._get(f"/rest/api/space/{key}")
        return f"Space {space.get('name') or key} is readable."

    # ------------------------------------------------------------ permissions

    async def space_readers(self, key: str) -> Principals:
        if self.cfg.flavour == "datacenter":
            return await self._dc_space_readers(key)
        return await self._cloud_space_readers(key)

    async def _dc_space_readers(self, key: str) -> Principals:
        out = Principals()
        space = await self._get(f"/rest/api/space/{key}", expand="permissions")
        for perm in space.get("permissions") or []:
            op = perm.get("operation") or {}
            if op.get("operation") != "read" or op.get("targetType") != "space":
                continue
            subjects = perm.get("subjects") or {}
            for u in (subjects.get("user") or {}).get("results") or []:
                out.users.add(str(u.get("email") or u.get("username")).lower())
            for g in (subjects.get("group") or {}).get("results") or []:
                out.groups.add(str(g.get("name")))
        return out

    async def _cloud_space_readers(self, key: str) -> Principals:
        out = Principals()
        found = await self._get("/api/v2/spaces", keys=key)
        spaces = found.get("results") or []
        if not spaces:
            return out
        path: str | None = f"/api/v2/spaces/{spaces[0]['id']}/permissions"
        params: dict[str, Any] = {"limit": 250}
        while path:
            data = await self._get(path, **params)
            for perm in data.get("results") or []:
                op = perm.get("operation") or {}
                if op.get("key") != "read" or op.get("targetType") != "space":
                    continue
                principal = perm.get("principal") or {}
                if principal.get("type") == "group":
                    group = await self._get("/rest/api/group/by-id", id=principal.get("id"))
                    out.groups.add(str(group.get("name")))
                elif principal.get("type") == "user":
                    user = await self._get("/rest/api/user", accountId=principal.get("id"))
                    if user.get("email"):
                        out.users.add(str(user["email"]).lower())
                    else:
                        self._unmapped.add(f"user {principal.get('id')} (e-mail hidden)")
            nxt = (data.get("_links") or {}).get("next")
            path, params = (nxt.removeprefix("/wiki"), {}) if nxt else (None, {})
        return out

    async def _user_ids(self) -> dict[str, UUID]:
        if self._emails is None:
            rows = await self.db.execute(
                sa.select(sa.func.lower(User.email), User.id).where(User.email.is_not(None))
            )
            self._emails = {str(e): i for e, i in rows.all()}
        return self._emails

    async def mapped(self, who: Principals) -> dict[str, list[str]]:
        emails = await self._user_ids()
        users = sorted(str(emails[u]) for u in who.users if u in emails)
        self._unmapped |= {f"user {u}" for u in who.users if u not in emails}
        groups = sorted({str(self.cfg.group_map[g]) for g in who.groups if g in self.cfg.group_map})
        self._unmapped |= {f"group {g}" for g in who.groups if g not in self.cfg.group_map}
        return {"users": users, "groups": groups}

    # ------------------------------------------------------------ pages

    async def _pages(self, key: str) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        start = 0
        while len(pages) < _MAX_PAGES:
            data = await self._get(
                "/rest/api/content",
                spaceKey=key,
                type="page",
                status="current",
                expand="body.storage,version,ancestors,"
                "restrictions.read.restrictions.user,restrictions.read.restrictions.group",
                limit=_PAGE,
                start=start,
            )
            results = data.get("results") or []
            pages += results
            if len(results) < _PAGE:
                return pages
            start += len(results)
        raise RuntimeError(f"space {key} has more than {_MAX_PAGES} pages")

    async def entries(self) -> AsyncIterator[Entry]:
        for key in self.cfg.spaces:
            space = await self.space_readers(key)
            pages = await self._pages(key)
            own = {str(p["id"]): _restriction(p) for p in pages}
            for page in pages:
                who = space
                chain = [str(a.get("id")) for a in page.get("ancestors") or []] + [str(page["id"])]
                for pid in chain:
                    rule = own.get(pid)
                    if rule is not None:
                        who = who.narrowed(rule)
                title = str(page.get("title") or page["id"])
                storage = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
                body = (
                    f"<html><head><title>{html.escape(title)}</title></head><body>"
                    f"<h1>{html.escape(title)}</h1>{storage}</body></html>"
                ).encode()
                version = page.get("version") or {}
                when = version.get("when")
                folders = "/".join(str(a.get("title")) for a in page.get("ancestors") or [])
                webui = (page.get("_links") or {}).get("webui")
                yield Entry(
                    external_id=f"{key}/{page['id']}",
                    path=f"{key}/{folders}/{title}".replace("//", "/"),
                    name=title.replace("/", "-")[:200] + ".html",
                    url=f"{self.base}{webui}" if webui else None,
                    version=str(version.get("number")) if version.get("number") else None,
                    size=len(body),
                    modified=datetime.fromisoformat(when.replace("Z", "+00:00")) if when else None,
                    content=body,
                    acl=await self.mapped(who),
                )
        self.listed_all = True

    async def _no_download(self, entry: Entry) -> bytes:
        raise RuntimeError(f"{entry.external_id} was not read with its page")

    def listing(self) -> Listing:
        return Listing(
            entries=self.entries(),
            download=self._no_download,
            complete=lambda: self.listed_all,
            unmapped=lambda: self._unmapped,
        )
