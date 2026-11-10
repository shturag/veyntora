# 0013 · Hosted model APIs for local development, Providers page, SharePoint connector

Status: accepted · 2026-10-30

## No model servers hosted locally

The product owner decided that local development hosts no model servers. Embeddings and reranking use provider APIs with keys, as the LLM already does (ADR 0010).

- The TEI embedder and reranker moved to the opt-in compose profile `local-models`; the status page checks them only when `VEY_TEI_*_URL` are set. On a 16 GB Docker VM they need about 5 GB and 6 GB (CPU ONNX Runtime keeps its warm-up allocation even with `--max-batch-tokens 1024`), more than is left beside the rest of the stack.
- New adapters (`veyntora_providers/adapters/hosted.py`):
  - `voyage`: Voyage AI embeddings and reranker, always external. It has separate query and document embeddings: adapters may offer `embed_query`, and retrieval uses it.
  - `openai_compatible` embeddings: any `/embeddings` endpoint.
  - `cohere_compatible` reranker: Cohere, Jina, vLLM or LiteLLM `/rerank`.
- Errors carry the HTTP status only, never the key or the document text. HTTP 429 and 5xx are retryable.
- The reranker scores the chunk itself, not its parent section; the parent still goes to the model.
- Production keeps self-hosted TEI/vLLM. Docling, Qdrant and ClamAV still run locally: they are services, not hosted models.

## Documents only reach an external provider with the data rule

Draft pipelines are indexed before publishing (ADR 0011), so an external embedder would receive document text before anyone could approve it. Ingestion now skips a profile whose parser, embedder or vector store is external unless the chatbot's data rule lists the provider and PII masking is switched off (masking arrives with the pipeline editor (ADR 0015–0017)). The same rule applies at publish and at run time (ADR 0012).

## Providers page pulled forward

The product owner wants keys entered in the admin console instead of the CLI. The Providers list (by capability, hosting, key last 4, health), the editor (name, endpoint, model, replace key, test connection) and Add provider are built now. The adapter choices come from the backend registry (`GET /v1/admin/providers/adapters`). Keys stay write-only (ADR 0004). Fallbacks, rotation grace periods, usage and cost come with the rest of the pipeline editor (ADR 0015–0017).

## SharePoint connector

- **Access:** Microsoft Graph with the client-credentials grant. The app needs `Sites.Selected` on the site or `Sites.Read.All`.
- **Settings and secret:** admins enter tenant, client id, client secret, site address, folders, schedule and group mapping in the console. The secret goes to OpenBao (`sources/<id>`); only its last 4 characters and expiry are kept.
- **Connection test:** runs in a worker, like provider tests.
- **Sync:**
  - per-library delta queries; the delta link is kept per library, so a failure later does not refetch earlier libraries;
  - files are matched on `documents.external_id` (drive/item), not the path, so renames keep their document;
  - `external_version` (cTag) avoids downloading unchanged files;
  - originals are stored in object storage for the source viewer;
  - deleted items are removed from every index.
- **Permissions, fail closed:**
  - users are matched by e-mail address;
  - Entra groups (`entra:<id>`) and SharePoint groups (`site:<name>`) are matched through the source's group mapping;
  - everything else, such as sharing links, unknown users and unmapped groups, is dropped and listed on the source page;
  - a document without mapped readers is visible to nobody.
- **Scanning:** SharePoint Online scans uploads itself, so documents are marked `not_required`.
- **Schedules:** presets (hourly, every 4 hours, daily 06:00 UTC), checked every minute by the scheduler.
- **Not yet tested against a live tenant.** Tests use mocked Graph responses in the documented shapes. This work is reported complete only after a live run.
