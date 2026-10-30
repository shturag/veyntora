# 0010 · Retrieval and provider adapters (Phase 1)

Status: accepted · 2026-10-30 · Phase 1

## External LLM for local development

There is no GPU on the development machine, so vLLM cannot run there. The product owner chose an external API key for local development. Production keeps vLLM (self-hosted).

- The **`anthropic` adapter** calls the Anthropic Messages API with the official SDK (`anthropic` 2.3.0, streaming). The key is read from OpenBao **at call time** by graphs and workers. It does not go through LiteLLM, because LiteLLM would keep its own copy of the key in its database, against ADR 0004.
- The instance must be `hosting: external` (enforced). Every request that uses it is marked as external egress, and a chatbot may use it only with a governance rule (`governance_rules.allowed_external_instance_ids`).
- No sampling parameters: current Claude models reject `temperature`. Answer depth is set with `options.effort` (default `low` for fast answers). Server-side refusal fallback is on by default (`fallbacks: "default"`) and can be switched off in the instance options.
- The model id is configuration on the instance, never code.

## Hybrid search

- Dense vectors: BGE-M3 on TEI, 1024 dimensions, self-hosted.
- Sparse side: TEI cannot serve BGE-M3's sparse head, so we use **Qdrant's server-side BM25** (`qdrant/bm25`, language from `options.bm25_language`, default German stemming) on the chunk text.
- Fusion: **weighted RRF** in Qdrant (`Rrf.weights` = dense weight, 1 − dense weight). The dense weight on the Pipeline page therefore works.
- **ACL filter:** every chunk carries `acl` (principals `user:<uuid>` / `group:<uuid>`). Each search filters on the caller's principals inside **both** prefetches and in the final query. An empty principal set returns nothing without querying. Points without an `acl` are refused at upsert. Revoking access is a payload update and takes effect immediately.

## Parsing and chunking

The "structure-aware" strategy uses docling-serve's hybrid chunker (`/v1/chunk/hybrid/file`). It follows headings, lists and tables and caps chunks by the embedding model's tokenizer (`BAAI/bge-m3`). The "fixed" strategy chunks the parser's sections in our code. "Semantic" arrives with the Pipeline pages (Phase 2). The hybrid chunker does not overlap chunks; overlap applies to fixed chunking.

## Test connection

The API cannot read keys, so "Test connection" queues the instance id (Valkey list). A worker holding the read-only runtime token runs the adapter's health check and the shared contract suite, and writes `health_status`/`health_detail`.

## Adding providers before the Providers UI (Phase 2)

`POST /v1/admin/providers` (area `providers`, editor) and `veyntora-api providers add|list|test`. The CLI reads keys from a hidden prompt or stdin, never from arguments, so they don't end up in shell history.
