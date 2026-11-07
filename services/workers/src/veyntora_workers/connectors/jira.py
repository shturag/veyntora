"""Jira Cloud and Data Center: issues of the chosen projects as knowledge (by default the
solved ones), with their description and comments.

- Issues come from the search API (Cloud: `/rest/api/3/search/jql`, paged by token;
  Data Center: `/rest/api/2/search`), rendered as HTML (`expand=renderedFields`). The
  update time tells changed issues apart. Cloud signs in with an e-mail and API token,
  Data Center with a personal access token.
- Who may read: the source's readers and folder rules ("PROJECT/…"); Jira's permission
  schemes are not mapped. Issues with a security level are left out unless the admin
  includes them (fail closed).
- Jira Service Management's knowledge base lives in Confluence: connect that space.
"""

from __future__ import annotations

import html
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
from veyntora_api.knowledge.connectors import JiraSettings

from veyntora_workers.connectors.listing import Entry, Listing

_PAGE = 100
_FIELDS = "summary,description,comment,updated,security,project,issuetype,status,resolution"


def jql_of(cfg: JiraSettings) -> str:
    projects = ", ".join(f'"{k}"' for k in cfg.projects)
    extra = f" AND ({cfg.jql.strip()})" if cfg.jql.strip() else ""
    return f"project in ({projects}){extra} ORDER BY key ASC"


def _when(value: str) -> datetime | None:
    # Jira writes 2026-10-01T08:00:00.000+0200.
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z") if value else None
    except ValueError:
        return None


class JiraReader:
    def __init__(
        self,
        cfg: JiraSettings,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cfg = cfg
        self.base = cfg.base_url.rstrip("/")
        auth: httpx.Auth | None = None
        headers = {"Accept": "application/json"}
        if cfg.flavour == "cloud":
            auth = httpx.BasicAuth(cfg.email or "", token)
        else:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.AsyncClient(timeout=60, auth=auth, headers=headers, transport=transport)
        self.listed_all = False

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        res = await self.http.get(f"{self.base}{path}", params=params or None)
        res.raise_for_status()
        data: dict[str, Any] = res.json()
        return data

    async def check(self) -> str:
        project = await self._get(f"/rest/api/2/project/{self.cfg.projects[0]}")
        return f"Project {project.get('name') or self.cfg.projects[0]} is readable."

    async def _pages(self) -> AsyncIterator[list[dict[str, Any]]]:
        params: dict[str, Any] = {
            "jql": jql_of(self.cfg),
            "fields": _FIELDS,
            "expand": "renderedFields",
            "maxResults": _PAGE,
        }
        if self.cfg.flavour == "cloud":
            while True:
                data = await self._get("/rest/api/3/search/jql", **params)
                yield data.get("issues") or []
                token = data.get("nextPageToken")
                if data.get("isLast", not token) or not token:
                    return
                params["nextPageToken"] = token
        start = 0
        while True:
            data = await self._get("/rest/api/2/search", **params, startAt=start)
            issues = data.get("issues") or []
            yield issues
            start += len(issues)
            if not issues or start >= int(data.get("total") or 0):
                return

    async def entries(self) -> AsyncIterator[Entry]:
        count = 0
        async for issues in self._pages():
            for issue in issues:
                count += 1
                if count > self.cfg.max_issues:
                    return  # not complete: nothing is removed
                fields = issue.get("fields") or {}
                if fields.get("security") and not self.cfg.include_secured:
                    continue
                yield self._entry(issue)
        self.listed_all = True

    def _entry(self, issue: dict[str, Any]) -> Entry:
        fields = issue.get("fields") or {}
        rendered = issue.get("renderedFields") or {}
        key = str(issue["key"])
        title = f"{key}: {fields.get('summary') or ''}".strip()
        facts = " · ".join(
            str((fields.get(f) or {}).get("name"))
            for f in ("issuetype", "status", "resolution")
            if (fields.get(f) or {}).get("name")
        )
        parts = [
            f"<html><head><title>{html.escape(title)}</title></head><body>",
            f"<h1>{html.escape(title)}</h1><p>{html.escape(facts)}</p>",
            str(rendered.get("description") or ""),
        ]
        if self.cfg.include_comments:
            raw = ((fields.get("comment") or {}).get("comments")) or []
            shown = ((rendered.get("comment") or {}).get("comments")) or []
            for i, comment in enumerate(shown):
                author = ((raw[i] if i < len(raw) else {}).get("author") or {}).get(
                    "displayName"
                ) or ""
                parts.append(f"<h2>{html.escape(str(author))}</h2>{comment.get('body') or ''}")
        body = ("".join(parts) + "</body></html>").encode()
        project = str((fields.get("project") or {}).get("key") or key.split("-", maxsplit=1)[0])
        updated = str(fields.get("updated") or "")
        return Entry(
            external_id=str(issue.get("id") or key),
            path=f"{project}/{key}",
            name=f"{title.replace('/', '-')}"[:200] + ".html",
            url=f"{self.base}/browse/{key}",
            version=updated or None,
            size=len(body),
            modified=_when(updated),
            content=body,
        )

    async def _no_download(self, entry: Entry) -> bytes:
        raise RuntimeError(f"{entry.external_id} was read with its listing")

    def listing(self) -> Listing:
        return Listing(
            entries=self.entries(), download=self._no_download, complete=lambda: self.listed_all
        )
