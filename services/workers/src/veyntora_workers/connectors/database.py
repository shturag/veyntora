"""Databases (PostgreSQL, SQL Server, MySQL/MariaDB, Oracle): each row of a read-only
query becomes a Markdown document.

- The query must be one SELECT (checked when saved). It runs in a read-only transaction
  where the engine has one (PostgreSQL, MySQL, Oracle) and is always rolled back; use a
  database account that can only read.
- At most `max_rows` rows are read; when a query returns more, the listing counts as
  incomplete and nothing is removed.
- Readers: the source's, or per row from `group_column`, whose value names a Veyntora
  group (by name or id); rows whose value matches no group are readable by nobody and
  the value is listed on the source.
- A row's content hash tells changed rows apart.

Drivers: asyncpg, python-tds (synchronous, run in a thread), aiomysql, python-oracledb
in thin mode (no Oracle client needed).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_api.db.models.identity import Group
from veyntora_api.knowledge.connectors import DatabaseSettings

from veyntora_workers.connectors.listing import Entry, Listing

Row = dict[str, Any]


async def _postgresql(cfg: DatabaseSettings, password: str, limit: int) -> list[Row]:
    import asyncpg  # noqa: PLC0415

    conn = await asyncpg.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.username,
        password=password,
        database=cfg.database,
        timeout=15,
    )
    try:
        async with conn.transaction(readonly=True):
            rows = []
            async for r in conn.cursor(cfg.query):
                rows.append(dict(r))
                if len(rows) >= limit:
                    break
            return rows
    finally:
        await conn.close()


async def _mysql(cfg: DatabaseSettings, password: str, limit: int) -> list[Row]:
    import aiomysql  # noqa: PLC0415

    conn = await aiomysql.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.username,
        password=password,
        db=cfg.database,
        connect_timeout=15,
        autocommit=False,
    )
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("START TRANSACTION READ ONLY")
            await cur.execute(cfg.query)
            rows: list[Row] = list(await cur.fetchmany(limit))
        await conn.rollback()
        return rows
    finally:
        conn.close()


def _sqlserver_sync(cfg: DatabaseSettings, password: str, limit: int) -> list[Row]:
    import pytds  # noqa: PLC0415

    with pytds.connect(
        server=cfg.host,
        port=cfg.port,
        database=cfg.database,
        user=cfg.username,
        password=password,
        login_timeout=15,
        autocommit=False,
        as_dict=True,
    ) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(cfg.query)
                rows: list[Row] = list(cur.fetchmany(limit))
        finally:
            conn.rollback()
    return rows


async def _oracle(cfg: DatabaseSettings, password: str, limit: int) -> list[Row]:
    import oracledb  # noqa: PLC0415

    conn = await oracledb.connect_async(
        user=cfg.username,
        password=password,
        dsn=f"{cfg.host}:{cfg.port}/{cfg.database}",
        tcp_connect_timeout=15,
    )
    try:
        with conn.cursor() as cur:
            await cur.execute("SET TRANSACTION READ ONLY")
            await cur.execute(cfg.query)
            names = [d[0].lower() for d in cur.description or []]
            rows = [dict(zip(names, r, strict=True)) for r in await cur.fetchmany(limit)]
        await conn.rollback()
        return rows
    finally:
        await conn.close()


async def fetch(cfg: DatabaseSettings, password: str, limit: int) -> list[Row]:
    if cfg.engine == "postgresql":
        return await _postgresql(cfg, password, limit)
    if cfg.engine == "mysql":
        return await _mysql(cfg, password, limit)
    if cfg.engine == "sqlserver":
        return await asyncio.to_thread(_sqlserver_sync, cfg, password, limit)
    return await _oracle(cfg, password, limit)


def _value(row: Row, column: str) -> Any:
    """Column lookup that tolerates the engine's case (Oracle returns upper case)."""
    if column in row:
        return row[column]
    lowered = {k.lower(): v for k, v in row.items()}
    return lowered.get(column.lower())


def as_markdown(cfg: DatabaseSettings, row: Row) -> tuple[str, bytes]:
    title = str(_value(row, cfg.title_column) or _value(row, cfg.id_column))
    columns: Sequence[str] = cfg.text_columns or [
        c for c in row if c.lower() not in {cfg.id_column.lower(), (cfg.group_column or "").lower()}
    ]
    lines = [f"# {title}", ""]
    for c in columns:
        value = _value(row, c)
        if value is not None and str(value).strip():
            lines += [f"**{c}**: {value}", ""]
    return title, "\n".join(lines).encode()


class DatabaseReader:
    def __init__(self, cfg: DatabaseSettings, password: str, db: AsyncSession) -> None:
        self.cfg = cfg
        self._password = password
        self.db = db
        self.listed_all = False
        self._unmapped: set[str] = set()

    async def check(self) -> str:
        rows = await fetch(self.cfg, self._password, 1)
        if rows and _value(rows[0], self.cfg.id_column) is None:
            raise RuntimeError(f"the query has no column {self.cfg.id_column}")
        return f"Connected to {self.cfg.database}; the query returns rows."

    async def _groups(self) -> dict[str, UUID]:
        rows = (await self.db.execute(sa.select(Group.id, Group.name))).all()
        out = {str(n).lower(): i for i, n in rows}
        out.update({str(i): i for i, _ in rows})
        return out

    async def entries(self) -> AsyncIterator[Entry]:
        rows = await fetch(self.cfg, self._password, self.cfg.max_rows + 1)
        groups = await self._groups() if self.cfg.group_column else {}
        for row in rows[: self.cfg.max_rows]:
            key = _value(row, self.cfg.id_column)
            if key is None:
                continue
            title, body = as_markdown(self.cfg, row)
            acl = None
            if self.cfg.group_column:
                raw = str(_value(row, self.cfg.group_column) or "")
                gid = groups.get(raw.lower()) or groups.get(raw)
                if gid is None:
                    self._unmapped.add(f"group value {raw!r}")
                acl = {"users": [], "groups": [str(gid)] if gid else []}
            yield Entry(
                external_id=str(key),
                path=f"rows/{key}",
                name=f"{title.replace('/', '-')[:150]}.md",
                url=None,
                version=None,
                size=len(body),
                modified=None,
                content=body,
                acl=acl,
            )
        self.listed_all = len(rows) <= self.cfg.max_rows

    async def _no_download(self, entry: Entry) -> bytes:
        raise RuntimeError(f"row {entry.external_id} was not read with the query")

    def listing(self) -> Listing:
        return Listing(
            entries=self.entries(),
            download=self._no_download,
            complete=lambda: self.listed_all,
            unmapped=lambda: self._unmapped,
        )
