"""SharePoint Online through Microsoft Graph (app-only, client credentials).

The Entra app needs `Sites.Selected` (granted on the chosen site) or `Sites.Read.All`.
Files come from the site's document libraries via delta queries, so later syncs only fetch
changes. Permissions come from each item's `permissions`; they are mapped to Veyntora
principals and anything that cannot be mapped is dropped (fail closed):

- users by e-mail address;
- Entra groups by id, and SharePoint site groups by name (`site:<name>`), through the
  source's group mapping, which admins edit in the console.

Not tested against a live tenant yet (Phase 1 report).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"


class SharePointError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DriveItem:
    drive_id: str
    item_id: str
    path: str  # "Library/Folder/File.pdf"
    name: str
    web_url: str | None
    etag: str | None
    size: int | None
    modified: str | None
    deleted: bool = False


@dataclass(slots=True)
class Principals:
    users: set[str] = field(default_factory=set)  # e-mail addresses, lower case
    groups: set[str] = field(default_factory=set)  # "entra:<id>" or "site:<name>"
    unmapped: set[str] = field(default_factory=set)  # labels of sharing links etc.


class SharePointClient:
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        *,
        http: httpx.AsyncClient | None = None,
        graph: str = GRAPH,
        login: str = LOGIN,
    ) -> None:
        self._tenant = tenant_id
        self._client_id = client_id
        self._secret = client_secret
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        self._graph = graph.rstrip("/")
        self._login = login.rstrip("/")
        self._token: str | None = None

    async def close(self) -> None:
        await self._http.aclose()

    async def _auth(self) -> dict[str, str]:
        if self._token is None:
            res = await self._http.post(
                f"{self._login}/{quote(self._tenant)}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
            )
            if res.status_code != 200:
                # Entra's error code only; the body can echo request details.
                code = (res.json() if res.content else {}).get("error", f"HTTP {res.status_code}")
                raise SharePointError(f"sign-in to Microsoft Entra failed: {code}")
            self._token = str(res.json()["access_token"])
        return {"authorization": f"Bearer {self._token}"}

    async def _get(self, url: str) -> dict[str, Any]:
        full = url if url.startswith("https://") else f"{self._graph}{url}"
        res = await self._http.get(full, headers=await self._auth())
        if res.status_code == 429 or res.status_code >= 500:
            raise httpx.TransportError(f"Microsoft Graph is busy (HTTP {res.status_code})")
        if res.status_code != 200:
            error = (res.json() if res.content else {}).get("error", {})
            raise SharePointError(
                f"Microsoft Graph refused {urlsplit(full).path}: "
                f"{error.get('code', res.status_code)}"
            )
        body: dict[str, Any] = res.json()
        return body

    async def site_id(self, site_url: str) -> str:
        parts = urlsplit(site_url)
        if parts.scheme != "https" or not parts.hostname:
            raise SharePointError("the site address must start with https://")
        path = parts.path.rstrip("/")
        site = await self._get(f"/sites/{parts.hostname}:{path or '/'}")
        return str(site["id"])

    async def drives(self, site_id: str) -> list[dict[str, Any]]:
        return list((await self._get(f"/sites/{site_id}/drives")).get("value", []))

    async def delta(
        self, drive: dict[str, Any], link: str | None
    ) -> AsyncIterator[DriveItem | str]:
        """Changed files of a library; yields items, then the new delta link (a str)."""
        url: str | None = link or f"/drives/{drive['id']}/root/delta"
        prefix = f"/drives/{drive['id']}/root:"
        while url:
            page = await self._get(url)
            for item in page.get("value", []):
                if "folder" in item or "root" in item:
                    continue
                if "deleted" not in item and "file" not in item:
                    continue
                parent = str((item.get("parentReference") or {}).get("path") or prefix)
                folder = parent.removeprefix(prefix).strip("/")
                path = "/".join(
                    p for p in (drive.get("name", ""), folder, item.get("name", "")) if p
                )
                yield DriveItem(
                    drive_id=str(drive["id"]),
                    item_id=str(item["id"]),
                    path=path,
                    name=str(item.get("name") or ""),
                    web_url=item.get("webUrl"),
                    etag=item.get("cTag") or item.get("eTag"),
                    size=item.get("size"),
                    modified=item.get("lastModifiedDateTime"),
                    deleted="deleted" in item,
                )
            if "@odata.deltaLink" in page:
                yield str(page["@odata.deltaLink"])
                return
            url = page.get("@odata.nextLink")

    async def permissions(self, item: DriveItem) -> Principals:
        out = Principals()
        url: str | None = f"/drives/{item.drive_id}/items/{item.item_id}/permissions"
        while url:
            page = await self._get(url)
            for perm in page.get("value", []):
                identities = [perm.get("grantedToV2"), *(perm.get("grantedToIdentitiesV2") or [])]
                for ident in filter(None, identities):
                    user = ident.get("user") or {}
                    group = ident.get("group") or {}
                    site_group = ident.get("siteGroup") or {}
                    if email := (user.get("email") or ident.get("siteUser", {}).get("email")):
                        out.users.add(str(email).lower())
                    elif group.get("id"):
                        out.groups.add(f"entra:{group['id']}")
                    elif site_group.get("displayName"):
                        out.groups.add(f"site:{site_group['displayName']}")
                    else:
                        out.unmapped.add(str(user.get("displayName") or "unknown identity"))
                if perm.get("link") and not identities[1:]:
                    out.unmapped.add(f"sharing link ({perm['link'].get('scope', 'unknown')})")
            url = page.get("@odata.nextLink")
        return out

    async def download(self, item: DriveItem) -> bytes:
        res = await self._http.get(
            f"{self._graph}/drives/{item.drive_id}/items/{item.item_id}/content",
            headers=await self._auth(),
            follow_redirects=True,
        )
        if res.status_code != 200:
            raise SharePointError(f"download of {item.path} failed (HTTP {res.status_code})")
        return res.content

    async def check(self, site_url: str) -> str:
        """Sign in, find the site and its libraries. Returns a short description."""
        site = await self.site_id(site_url)
        drives = await self.drives(site)
        return f"{len(drives)} document libraries found"
