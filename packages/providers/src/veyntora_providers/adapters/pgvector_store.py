"""pgvector: chunks in PostgreSQL, for teams that would rather not run a separate vector database
(ADR 0042).

One table per collection in its own schema. Dense search uses cosine distance on an HNSW
index; keyword search uses PostgreSQL's full-text search (a tsvector column, any of the query's
words); the two are fused with weighted reciprocal-rank fusion, as Qdrant does.

Permission-aware retrieval lives here as with Qdrant: every query filters on the chunk's
`acl` array with the asking user's principals, in *both* searches, so a chunk the user may not
read is never a candidate. An empty principal set returns no hits without querying.

Endpoint: a PostgreSQL address, `postgresql://user@host:5432/database`; the password is the
instance's secret. Options: `schema` (default `veyntora_vectors`) and `text_search_config`
(default from `bm25_language`, as for Qdrant: `german`, or `english`, `simple`, ...).
"""

# Table, schema and text-search names are put into SQL only after _ident/_NAME checked them;
# every value is a query parameter.
# ruff: noqa: S608

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from veyntora_providers.instance import ProviderInstanceConfig
from veyntora_providers.interfaces import (
    AclFilter,
    Capability,
    HealthResult,
    Hit,
    HybridQuery,
    Point,
    StoredChunk,
)
from veyntora_providers.registry import register
from veyntora_providers.secrets import SecretReader

# Fields with their own column (filters on them use indexes); the rest are payload keys.
_COLUMNS = ("document_id", "source_id", "profile")
_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_RRF_K = 60


def _ident(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"{name!r} is not a valid schema or collection name")
    return f'"{name}"'


def _vector(values: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def _text(value: str | int | bool) -> str:
    """A payload value as `->>` returns it from JSON."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class PgvectorStore:
    def __init__(self, config: ProviderInstanceConfig, secrets: SecretReader) -> None:
        if not config.endpoint:
            raise ValueError("pgvector instances need an endpoint (postgresql://user@host/db)")
        if urlsplit(config.endpoint).scheme not in {"postgresql", "postgres"}:
            raise ValueError("the endpoint is a PostgreSQL address: postgresql://user@host/db")
        self._config = config
        self._secrets = secrets
        self._pool: asyncpg.Pool | None = None
        self._schema = _ident(str(config.options.get("schema", "veyntora_vectors")))
        language = str(config.options.get("bm25_language", "german"))
        self._ts = str(config.options.get("text_search_config", language))
        if not _NAME.match(self._ts):
            raise ValueError(f"{self._ts!r} is not a text search configuration")
        self._ready: set[str] = set()

    async def _db(self) -> asyncpg.Pool:
        if self._pool is None:
            password = (
                await self._secrets.read(self._config.secret_ref)
                if self._config.secret_ref
                else None
            )
            parts = urlsplit(str(self._config.endpoint))
            dsn = urlunsplit(("postgresql", *parts[1:]))
            self._pool = await asyncpg.create_pool(
                dsn, password=password, min_size=0, max_size=5, command_timeout=30
            )
        return self._pool

    def _table(self, collection: str) -> str:
        return f"{self._schema}.{_ident(collection)}"

    async def _exists(self, collection: str) -> bool:
        if collection in self._ready:
            return True
        pool = await self._db()
        found = await pool.fetchval(
            "SELECT to_regclass($1) IS NOT NULL", f"{self._schema}.{_ident(collection)}"
        )
        if found:
            self._ready.add(collection)
        return bool(found)

    async def ensure_collection(self, collection: str, dimensions: int) -> None:
        pool = await self._db()
        table = self._table(collection)
        async with pool.acquire() as con:
            if not await con.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'vector'"):
                try:
                    await con.execute("CREATE EXTENSION IF NOT EXISTS vector")
                except asyncpg.PostgresError as exc:
                    raise ValueError(
                        "the pgvector extension is missing and this user may not create it: "
                        "run CREATE EXTENSION vector; as a database owner"
                    ) from exc
            if await self._exists(collection):
                size = await con.fetchval(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = $1::regclass AND attname = 'embedding'",
                    table,
                )
                if size != dimensions:
                    raise ValueError(
                        f"collection {collection} has {size}-dimensional vectors, "
                        f"the embedding has {dimensions}"
                    )
                return
            async with con.transaction():
                await con.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
                await con.execute(
                    f"""CREATE TABLE IF NOT EXISTS {table} (
                        id text PRIMARY KEY,
                        document_id text NOT NULL,
                        source_id text,
                        profile text,
                        acl text[] NOT NULL,
                        payload jsonb NOT NULL,
                        body text,
                        tsv tsvector GENERATED ALWAYS AS
                            (to_tsvector('{self._ts}'::regconfig, coalesce(body, ''))) STORED,
                        embedding vector({int(dimensions)}) NOT NULL
                    )"""
                )
                name = collection[:40]
                await con.execute(f"CREATE INDEX IF NOT EXISTS {name}_doc ON {table} (document_id)")
                await con.execute(
                    f"CREATE INDEX IF NOT EXISTS {name}_acl ON {table} USING gin (acl)"
                )
                await con.execute(
                    f"CREATE INDEX IF NOT EXISTS {name}_tsv ON {table} USING gin (tsv)"
                )
                await con.execute(
                    f"CREATE INDEX IF NOT EXISTS {name}_vec ON {table} "
                    "USING hnsw (embedding vector_cosine_ops)"
                )
        self._ready.add(collection)

    async def upsert(self, collection: str, points: Sequence[Point]) -> None:
        if not points:
            return
        rows = []
        for p in points:
            acl = p.payload.get("acl")
            if not isinstance(acl, list | tuple):
                raise ValueError(f"point {p.id} has no ACL; refusing to index it")
            rows.append(
                (
                    p.id,
                    str(p.payload.get("document_id") or ""),
                    _opt(p.payload.get("source_id")),
                    _opt(p.payload.get("profile")),
                    [str(x) for x in acl],
                    json.dumps(dict(p.payload), default=str),
                    p.text,
                    _vector(p.dense),
                )
            )
        pool = await self._db()
        await pool.executemany(
            f"""INSERT INTO {self._table(collection)}
                (id, document_id, source_id, profile, acl, payload, body, embedding)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8::vector)
                ON CONFLICT (id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source_id = EXCLUDED.source_id,
                    profile = EXCLUDED.profile, acl = EXCLUDED.acl, payload = EXCLUDED.payload,
                    body = EXCLUDED.body, embedding = EXCLUDED.embedding""",
            rows,
        )

    async def delete_by_document(
        self, collection: str, document_id: str, profile: str | None = None
    ) -> None:
        if not await self._exists(collection):
            return
        pool = await self._db()
        if profile is None:
            await pool.execute(
                f"DELETE FROM {self._table(collection)} WHERE document_id = $1", document_id
            )
        else:
            await pool.execute(
                f"DELETE FROM {self._table(collection)} WHERE document_id = $1 AND profile = $2",
                document_id,
                profile,
            )

    async def set_acl(self, collection: str, document_id: str, principals: Sequence[str]) -> None:
        if not await self._exists(collection):
            return
        pool = await self._db()
        await pool.execute(
            f"""UPDATE {self._table(collection)}
                SET acl = $2, payload = jsonb_set(payload, '{{acl}}', to_jsonb($2::text[]))
                WHERE document_id = $1""",
            document_id,
            list(principals),
        )

    def _where(self, query: HybridQuery, acl_filter: AclFilter) -> tuple[str, list[Any]]:
        """The ACL and the admin's filters, as SQL with numbered arguments from $1."""
        args: list[Any] = [list(acl_filter.principals)]
        clauses = ["acl && $1::text[]"]
        for key, values in query.must_match.items():
            args.append([_text(v) for v in values])
            n = len(args)
            if key in _COLUMNS:
                clauses.append(f"{key} = ANY(${n}::text[])")
            elif key == "acl":
                clauses.append(f"acl && ${n}::text[]")
            else:
                if not _NAME.match(key):
                    raise ValueError(f"{key!r} is not a filterable field")
                # A list in the payload matches when any of its items does, as in Qdrant.
                clauses.append(
                    f"(payload->>'{key}' = ANY(${n}::text[]) OR "
                    f"(jsonb_typeof(payload->'{key}') = 'array' AND "
                    f"payload->'{key}' ?| ${n}::text[]))"
                )
        return " AND ".join(clauses), args

    async def hybrid_search(
        self, collection: str, query: HybridQuery, acl_filter: AclFilter, k: int
    ) -> list[Hit]:
        if acl_filter.is_empty() or not await self._exists(collection):
            return []
        pool = await self._db()
        table = self._table(collection)
        where, args = self._where(query, acl_filter)
        ranked: list[tuple[list[asyncpg.Record], float]] = []
        if query.dense is not None:
            n = len(args) + 1
            rows = await pool.fetch(
                f"""SELECT id, payload, 1 - (embedding <=> ${n}::vector) AS score
                    FROM {table} WHERE {where}
                    ORDER BY embedding <=> ${n}::vector LIMIT {int(k)}""",
                *args,
                _vector(query.dense),
            )
            ranked.append((rows, query.dense_weight))
        if query.sparse and query.text:
            n = len(args) + 1
            # Any of the query's words, like BM25 (plainto_tsquery would need all of them).
            words = f"replace(plainto_tsquery('{self._ts}'::regconfig, ${n})::text, '&', '|')"
            rows = await pool.fetch(
                f"""SELECT id, payload, ts_rank_cd(tsv, q) AS score
                    FROM {table}, to_tsquery('{self._ts}'::regconfig, {words}) AS q
                    WHERE {where} AND q::text <> '' AND tsv @@ q
                    ORDER BY score DESC LIMIT {int(k)}""",
                *args,
                query.text,
            )
            ranked.append((rows, 1.0 - query.dense_weight))
        if not ranked:
            return []
        if len(ranked) == 1:
            return [_hit(r, float(r["score"])) for r in ranked[0][0]]
        # Weighted reciprocal-rank fusion of both lists.
        fused: dict[str, tuple[float, asyncpg.Record]] = {}
        for rows, weight in ranked:
            for rank, r in enumerate(rows, 1):
                score, _ = fused.get(r["id"], (0.0, r))
                fused[r["id"]] = (score + weight / (_RRF_K + rank), r)
        best = sorted(fused.values(), key=lambda x: x[0], reverse=True)[:k]
        return [_hit(r, score) for score, r in best]

    async def chunks_of(self, collection: str, document_id: str, limit: int) -> list[StoredChunk]:
        """A document's chunks with their dense vectors (knowledge health scan only)."""
        if not await self._exists(collection):
            return []
        pool = await self._db()
        rows = await pool.fetch(
            f"""SELECT id, payload, embedding::text AS dense FROM {self._table(collection)}
                WHERE document_id = $1 LIMIT {int(limit)}""",
            document_id,
        )
        out = []
        for r in rows:
            payload = _payload(r)
            out.append(
                StoredChunk(
                    id=r["id"],
                    text=str(payload.get("text") or ""),
                    dense=[float(x) for x in r["dense"].strip("[]").split(",") if x],
                    payload=payload,
                )
            )
        return out

    async def nearest(
        self, collection: str, dense: list[float], k: int, exclude_document_id: str
    ) -> list[Hit]:
        """The most similar chunks of other documents (knowledge health scan only)."""
        if not await self._exists(collection):
            return []
        pool = await self._db()
        rows = await pool.fetch(
            f"""SELECT id, payload, 1 - (embedding <=> $1::vector) AS score
                FROM {self._table(collection)} WHERE document_id <> $2
                ORDER BY embedding <=> $1::vector LIMIT {int(k)}""",
            _vector(dense),
            exclude_document_id,
        )
        return [_hit(r, float(r["score"])) for r in rows]

    async def health(self) -> HealthResult:
        start = time.perf_counter()
        try:
            pool = await self._db()
            available = await pool.fetchval(
                "SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'"
            )
        except (OSError, asyncpg.PostgresError, ValueError) as exc:
            return HealthResult(False, (time.perf_counter() - start) * 1000, type(exc).__name__)
        ms = (time.perf_counter() - start) * 1000
        if not available:
            return HealthResult(False, ms, "the pgvector extension is not installed on the server")
        return HealthResult(True, ms)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()


def _opt(value: Any) -> str | None:
    return None if value is None else str(value)


def _payload(row: asyncpg.Record) -> dict[str, Any]:
    raw = row["payload"]
    value = json.loads(raw) if isinstance(raw, str) else raw
    return dict(value or {})


def _hit(row: asyncpg.Record, score: float) -> Hit:
    return Hit(id=row["id"], score=score, payload=_payload(row))


@register(Capability.VECTOR_STORE, "pgvector")
def _factory(config: ProviderInstanceConfig, secrets: SecretReader) -> PgvectorStore:
    return PgvectorStore(config, secrets)
