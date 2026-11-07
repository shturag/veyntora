"""SharePoint Server (2016, 2019, Subscription Edition): document libraries, with their
permissions.

- Files come from the REST API (`/_api/web/lists(…)/items`); the modification time tells
  changed files apart. Sign-in is Windows (NTLM, through pyspnego, which the file share
  connector already uses) or basic sign-in over HTTPS where IIS allows it.
- Who may read a file (fail closed): the role assignments with "View Items" of the
  file itself when it has its own, else of the nearest folder that has its own, else of
  the library. Members map to Veyntora:
  - users by e-mail;
  - Active Directory groups and claims (all users, all Windows users) through the group
    map, by login name, SID or title;
  - SharePoint groups through the group map by name, else by their members (users by
    e-mail, AD groups through the map).
  Whatever cannot be mapped is dropped and listed on the source.

Not tested against a live SharePoint Server yet; the responses follow the documented
shapes.
"""

from __future__ import annotations

import base64
import posixpath
from collections.abc import AsyncIterator, Generator
from datetime import datetime
from typing import Any
from urllib.parse import quote, unquote, urlsplit
from uuid import UUID

import httpx
import spnego
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.knowledge.connectors import SharePointServerSettings

from veyntora_workers.connectors.listing import Entry, Listing
from veyntora_workers.connectors.principals import PrincipalMap

VIEW_LIST_ITEMS = 0x1
_USER, _AD_GROUP, _SP_GROUP = 1, 4, 8
_PAGE = 500
_MAX_FILES = 100_000
_FIELDS = "Id,FileRef,FileLeafRef,FSObjType,Modified,File_x0020_Size,HasUniqueRoleAssignments"


class NtlmAuth(httpx.Auth):
    """Windows sign-in: negotiate, answer the server's challenge, send the request."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        ctx = spnego.client(
            self.username,
            self.password,
            hostname=request.url.host,
            service="HTTP",
            protocol="ntlm",
        )
        request.headers["Authorization"] = "NTLM " + base64.b64encode(ctx.step() or b"").decode()
        response = yield request
        challenge = next(
            (
                v.split(" ", 1)[1]
                for v in response.headers.get_list("www-authenticate")
                if v.startswith("NTLM ")
            ),
            None,
        )
        if response.status_code != 401 or challenge is None:
            return
        answer = ctx.step(base64.b64decode(challenge)) or b""
        request.headers["Authorization"] = "NTLM " + base64.b64encode(answer).decode()
        yield request


def can_read(binding: dict[str, Any]) -> bool:
    low = (binding.get("BasePermissions") or {}).get("Low")
    return bool(int(low or 0) & VIEW_LIST_ITEMS)


def _keys(member: dict[str, Any]) -> tuple[str, ...]:
    """What the group map may name a group or claim by: login name, SID, title."""
    login = str(member.get("LoginName") or "")
    sid = login.rsplit("|", 1)[-1] if "|" in login else ""
    return (login, sid, str(member.get("Title") or ""))


class SharePointServerReader:
    def __init__(
        self,
        cfg: SharePointServerSettings,
        password: str,
        db: AsyncSession,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cfg = cfg
        self.site = cfg.site_url.rstrip("/")
        parts = urlsplit(self.site)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        auth: httpx.Auth = (
            NtlmAuth(cfg.username, password)
            if cfg.auth == "ntlm"
            else httpx.BasicAuth(cfg.username, password)
        )
        self.http = httpx.AsyncClient(
            timeout=60,
            auth=auth,
            headers={"Accept": "application/json;odata=nometadata"},
            transport=transport,
        )
        self.map = PrincipalMap(db, cfg.group_map)
        self.listed_all = False
        self._web_path = ""
        self._sp_groups: dict[int, tuple[set[str], set[UUID]]] = {}

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, path: str) -> dict[str, Any]:
        res = await self.http.get(path if path.startswith("http") else f"{self.site}{path}")
        res.raise_for_status()
        data: dict[str, Any] = res.json()
        return data

    async def _all(self, path: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        url: str | None = path
        while url:
            data = await self._get(url)
            out += data.get("value") or []
            url = data.get("odata.nextLink")
        return out

    async def check(self) -> str:
        web = await self._get("/_api/web?$select=Title,ServerRelativeUrl")
        libraries = await self._libraries()
        return f"Site {web.get('Title')} is readable; {len(libraries)} document libraries."

    async def _libraries(self) -> list[dict[str, Any]]:
        found = await self._all(
            "/_api/web/lists?$filter=BaseTemplate eq 101 and Hidden eq false"
            "&$select=Id,Title,RootFolder/ServerRelativeUrl&$expand=RootFolder"
        )
        if not self.cfg.libraries:
            return found
        wanted = {t.lower() for t in self.cfg.libraries}
        chosen = [lib for lib in found if str(lib.get("Title")).lower() in wanted]
        if missing := wanted - {str(lib.get("Title")).lower() for lib in chosen}:
            raise RuntimeError(f"libraries not found: {', '.join(sorted(missing))}")
        return chosen

    # ------------------------------------------------------------ permissions

    async def _sp_group(self, gid: int) -> tuple[set[str], set[UUID]]:
        """Members of a SharePoint group: e-mails, and Veyntora groups of its AD groups."""
        if gid not in self._sp_groups:
            emails: set[str] = set()
            groups: set[UUID] = set()
            for m in await self._all(
                f"/_api/web/sitegroups/GetById({gid})/users"
                "?$select=LoginName,Title,Email,PrincipalType"
            ):
                kind = int(m.get("PrincipalType") or 0)
                if kind == _USER and m.get("Email"):
                    emails.add(str(m["Email"]))
                elif (mapped := self.map.group(*_keys(m))) is not None:
                    groups.add(mapped)
                else:
                    self.map.unmapped.add(f"group {m.get('Title') or m.get('LoginName')}")
            self._sp_groups[gid] = (emails, groups)
        return self._sp_groups[gid]

    async def readers(self, path: str) -> dict[str, list[str]]:
        """The mapped readers of a securable object (`…/RoleAssignments` is appended)."""
        emails: set[str] = set()
        groups: set[UUID] = set()
        unmapped: set[str] = set()
        for ra in await self._all(f"{path}/RoleAssignments?$expand=Member,RoleDefinitionBindings"):
            if not any(can_read(b) for b in ra.get("RoleDefinitionBindings") or []):
                continue
            member = ra.get("Member") or {}
            kind = int(member.get("PrincipalType") or 0)
            if (mapped := self.map.group(*_keys(member))) is not None:
                groups.add(mapped)
            elif kind == _USER:
                if member.get("Email"):
                    emails.add(str(member["Email"]))
                else:
                    unmapped.add(f"user {member.get('LoginName')} (no e-mail)")
            elif kind == _SP_GROUP:
                members, mapped_groups = await self._sp_group(int(member["Id"]))
                emails |= members
                groups |= mapped_groups
            else:
                unmapped.add(f"group {member.get('Title') or member.get('LoginName')}")
        return await self.map.acl(emails, groups, unmapped)

    # ------------------------------------------------------------ files

    def _included(self, rel: str) -> bool:
        if not self.cfg.include_paths:
            return True
        lowered = rel.lower()
        return any(lowered.startswith(p.lower() + "/") for p in self.cfg.include_paths)

    async def entries(self) -> AsyncIterator[Entry]:
        web = await self._get("/_api/web?$select=ServerRelativeUrl")
        self._web_path = str(web.get("ServerRelativeUrl") or "").rstrip("/")
        files = 0
        for lib in await self._libraries():
            path = f"/_api/web/lists(guid'{lib['Id']}')"
            items = await self._all(f"{path}/items?$select={_FIELDS}&$top={_PAGE}")
            library_acl = await self.readers(path)
            # Folders with permissions of their own; files below them inherit those.
            own: dict[str, dict[str, list[str]]] = {}
            for item in sorted(items, key=lambda i: str(i.get("FileRef"))):
                if int(item.get("FSObjType") or 0) == 1 and item.get("HasUniqueRoleAssignments"):
                    own[str(item["FileRef"])] = await self.readers(f"{path}/items({item['Id']})")
            for item in items:
                if int(item.get("FSObjType") or 0) != 0:
                    continue
                ref = str(item["FileRef"])
                rel = ref.removeprefix(self._web_path).strip("/")
                if not self._included(rel):
                    continue
                files += 1
                if files > _MAX_FILES:
                    return
                if item.get("HasUniqueRoleAssignments"):
                    acl = await self.readers(f"{path}/items({item['Id']})")
                else:
                    acl = self._inherited(ref, own) or library_acl
                size = item.get("File_x0020_Size")
                modified = str(item.get("Modified") or "")
                yield Entry(
                    external_id=f"{lib['Id']}/{item['Id']}",
                    path=rel,
                    name=str(item.get("FileLeafRef") or posixpath.basename(ref)),
                    url=f"{self.origin}{quote(ref)}",
                    version=modified or None,
                    size=int(str(size)) if str(size or "").isdigit() else None,
                    modified=(
                        datetime.fromisoformat(modified.replace("Z", "+00:00"))
                        if modified
                        else None
                    ),
                    acl=acl,
                )
        self.listed_all = True

    @staticmethod
    def _inherited(ref: str, own: dict[str, dict[str, list[str]]]) -> dict[str, list[str]] | None:
        folder = posixpath.dirname(ref)
        while folder and folder != "/":
            if folder in own:
                return own[folder]
            folder = posixpath.dirname(folder)
        return None

    async def download(self, entry: Entry) -> bytes:
        ref = unquote(urlsplit(entry.url or "").path)
        escaped = ref.replace("'", "''")
        res = await self.http.get(
            f"{self.site}/_api/web/GetFileByServerRelativeUrl('{escaped}')/$value"
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
