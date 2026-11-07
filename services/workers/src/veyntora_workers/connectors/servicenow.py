"""ServiceNow knowledge: published articles of the chosen knowledge bases.

- Articles come from the Table API (`kb_knowledge`): published, active and not past
  their "valid to" date. The modification count tells changed articles apart. The
  account needs read access to kb_knowledge, kb_knowledge_base and kb_uc_can_read_mtom
  (the "knowledge" role and a read ACL on that table, or a role that grants them).
- Who may read: the source's readers and folder rules ("knowledge base/category/…").
  ServiceNow's user criteria can be scripted, so Veyntora does not evaluate them: unless
  the admin includes restricted articles, an article with its own "Can read" criteria,
  or in a knowledge base with "Can read" criteria, is left out (fail closed).
"""

from __future__ import annotations

import html
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
from veyntora_api.knowledge.connectors import ServiceNowSettings

from veyntora_workers.connectors.listing import Entry, Listing

_PAGE = 100
_FIELDS = (
    "sys_id,number,short_description,text,sys_updated_on,sys_mod_count,"
    "can_read_user_criteria,kb_knowledge_base,kb_knowledge_base.title,kb_category.label"
)


class ServiceNowReader:
    def __init__(
        self,
        cfg: ServiceNowSettings,
        password: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cfg = cfg
        self.base = cfg.instance_url.rstrip("/")
        self.http = httpx.AsyncClient(
            timeout=60,
            auth=httpx.BasicAuth(cfg.username, password),
            headers={"Accept": "application/json"},
            transport=transport,
        )
        self.listed_all = False

    async def close(self) -> None:
        await self.http.aclose()

    async def _table(self, table: str, **params: Any) -> list[dict[str, Any]]:
        res = await self.http.get(
            f"{self.base}/api/now/table/{table}",
            params={"sysparm_exclude_reference_link": "true", **params},
        )
        res.raise_for_status()
        rows: list[dict[str, Any]] = res.json().get("result") or []
        return rows

    async def knowledge_bases(self) -> dict[str, str]:
        """sys_id -> title of the chosen (else every readable) knowledge base."""
        rows = await self._table(
            "kb_knowledge_base", sysparm_fields="sys_id,title", sysparm_limit=1000
        )
        found = {str(r["sys_id"]): str(r.get("title") or r["sys_id"]) for r in rows}
        if not self.cfg.knowledge_bases:
            return found
        wanted = {t.lower() for t in self.cfg.knowledge_bases}
        chosen = {i: t for i, t in found.items() if t.lower() in wanted}
        if missing := wanted - {t.lower() for t in chosen.values()}:
            raise RuntimeError(f"knowledge bases not found: {', '.join(sorted(missing))}")
        return chosen

    async def _restricted_bases(self, ids: list[str]) -> set[str]:
        rows = await self._table(
            "kb_uc_can_read_mtom",
            sysparm_query=f"kb_knowledge_baseIN{','.join(ids)}",
            sysparm_fields="kb_knowledge_base",
            sysparm_limit=10_000,
        )
        return {str(r.get("kb_knowledge_base")) for r in rows}

    async def check(self) -> str:
        bases = await self.knowledge_bases()
        return f"{len(bases)} knowledge bases are readable: {', '.join(sorted(bases.values()))}."

    async def entries(self) -> AsyncIterator[Entry]:
        bases = await self.knowledge_bases()
        if not bases:
            self.listed_all = True
            return
        restricted = (
            set() if self.cfg.include_restricted else await self._restricted_bases(list(bases))
        )
        query = (
            "workflow_state=published^active=true"
            f"^kb_knowledge_baseIN{','.join(bases)}"
            "^valid_to>=javascript:gs.beginningOfToday()^ORvalid_toISEMPTY^ORDERBYsys_id"
        )
        offset = count = 0
        while True:
            rows = await self._table(
                "kb_knowledge",
                sysparm_query=query,
                sysparm_fields=_FIELDS,
                sysparm_limit=_PAGE,
                sysparm_offset=offset,
            )
            for row in rows:
                count += 1
                if count > self.cfg.max_articles:
                    return  # not complete: nothing is removed
                if not self.cfg.include_restricted and (
                    row.get("can_read_user_criteria")
                    or str(row.get("kb_knowledge_base")) in restricted
                ):
                    continue
                yield self._entry(row)
            if len(rows) < _PAGE:
                break
            offset += len(rows)
        self.listed_all = True

    def _entry(self, row: dict[str, Any]) -> Entry:
        number = str(row.get("number") or row["sys_id"])
        title = str(row.get("short_description") or number)
        body = (
            f"<html><head><title>{html.escape(title)}</title></head><body>"
            f"<h1>{html.escape(title)}</h1>{row.get('text') or ''}</body></html>"
        ).encode()
        names = (row.get("kb_knowledge_base.title"), row.get("kb_category.label"))
        folder = "/".join(str(p).replace("/", "-") for p in names if p)
        when = str(row.get("sys_updated_on") or "")
        return Entry(
            external_id=str(row["sys_id"]),
            path=f"{folder}/{number}".lstrip("/"),
            name=f"{number} {title.replace('/', '-')}"[:200] + ".html",
            url=f"{self.base}/kb_view.do?sysparm_article={number}",
            version=str(row.get("sys_mod_count") or when) or None,
            size=len(body),
            modified=(
                datetime.strptime(when, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC) if when else None
            ),
            content=body,
        )

    async def _no_download(self, entry: Entry) -> bytes:
        raise RuntimeError(f"{entry.external_id} was read with its listing")

    def listing(self) -> Listing:
        return Listing(
            entries=self.entries(), download=self._no_download, complete=lambda: self.listed_all
        )
