# 0042 · pgvector as a second vector store

Status: accepted · 2026-11-10

## Context

Qdrant was the only vector store. Many companies already run PostgreSQL, back it up and watch it, and would rather keep the chunks there than run, secure and back up another database. pgvector adds vector search to PostgreSQL.

## Decision

**1. A `pgvector` adapter for the vector-store capability**, next to Qdrant, chosen per chatbot like any provider.
- **Endpoint:** a PostgreSQL address, `postgresql://user@host:5432/database`.
- **Password:** the instance's write-only secret (ADR 0004). An address with a password in it is refused, because endpoints are shown in the console.
- **Database:** any PostgreSQL with the extension; Veyntora's own database works too. The adapter creates the extension if the user may, otherwise it says to run `CREATE EXTENSION vector` as an owner.
- **No new dependency:** the client is `asyncpg`, which the API already uses.

**2. One table per collection** in its own schema (`veyntora_vectors` by default):
- **Columns:** document, source and profile for filters; the ACL as a text array; the payload as JSONB; the passage text with a generated `tsvector`; and the embedding.
- **Indexes:** HNSW with cosine distance for the embedding, GIN for the ACL and the text, B-tree for the document.

**3. Hybrid search as with Qdrant:**
- **Dense:** cosine similarity.
- **Keywords:** PostgreSQL full-text search with any of the query's words, in the text-search configuration of `bm25_language` (or `text_search_config`).
- **Fusion:** the two lists are fused with weighted reciprocal-rank fusion (dense weight from the pipeline).

**4. Permissions as with Qdrant.** Every query filters on the asking person's principals in both searches, so a passage they may not read is never a candidate; an empty set returns nothing without querying. Admin filters match columns or payload keys; a list in the payload matches when any of its items does.

**5. Knowledge health:** the adapter also provides the two maintenance reads (a document's chunks with vectors, and the nearest chunks of other documents).

## Consequences

- One database less to run for teams that prefer PostgreSQL. Qdrant stays the default for large collections and high query rates.
- Keyword search differs a little from Qdrant's BM25 (PostgreSQL ranks with `ts_rank_cd`), so scores aren't comparable between the two stores. Reranking evens this out.
- Moving a chatbot from one store to the other re-indexes its sources, as any change of index profile does.
- Tested against `pgvector/pgvector:0.8.7-pg16` in the test suite.
