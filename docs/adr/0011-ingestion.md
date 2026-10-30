# 0011 · Ingestion, index profiles and chatbot setup (Phase 1)

Status: accepted · 2026-10-30 · Phase 1

## Index profiles

Ingestion settings live in each chatbot's pipeline, but documents belong to sources that many chatbots share. The parts of a spec that decide what stored chunks look like (parser, embedding instance, vector store, chunking, OCR/tables/images, parent chunks, chunk metadata) form an **index profile** (`veyntora_spec.profile`). Its key is a hash of those settings.

- Chunks are stored per document and profile. The payload carries `profile`, `source_id`, `document_id` and `acl`. Chatbots with the same profile share chunks; changing chunking or the embedding model creates a new profile and a re-index instead of mixing incompatible chunks.
- One Qdrant collection per embedding instance (`vey_<id>`), so vector dimensions never mix.
- A source is indexed for the live, canary and current draft versions of every chatbot it is attached to, so a draft can be tried before publishing.
- `document_indexes` records each document/profile pair (status, chunk count, content hash), which makes re-runs idempotent.
- Retrieval searches only `profile = <own profile>` and `source_id ∈ <attached sources>`, on top of the ACL filter.

## Jobs

Jobs are rows in `ingest_jobs`. Workers claim the oldest queued job with `FOR UPDATE SKIP LOCKED` (beat tick every 3 s; stale ticks expire). This avoids Celery in the API and needs no extra queue, and a job can't be lost.

- Each document is row-locked while it is processed. Upload and reindex jobs on a busy document retry; source syncs skip it.
- Work is committed per document. Originals are deleted from S3 only after the commit that drops them.
- Failures of a dependency (virus scanner, parser, embedding server, OpenBao) put the job back with exponential backoff (15 s up to 15 min, 8 attempts). Content problems (unparseable file, wrong provider kind) fail the document with its reason.
- Jobs stuck in `running` for 30 minutes (dead worker) are requeued.

## Uploads and virus scanning

- Accepted types: PDF, DOCX, PPTX, XLSX, HTML, Markdown, text, CSV, PNG, JPEG, TIFF. The content must match the extension (magic bytes; UTF-8 for text). The size limit is `VEY_UPLOAD_MAX_BYTES` (50 MB).
- Originals go to S3 under `sources/{source}/{document}/{sha256}`. Uploading the same name replaces the document; identical content that is already queued or indexed is not queued again.
- **ClamAV** (new container, `clamav/clamav-debian:1.5.1`, clamd INSTREAM on 3310) scans every upload before parsing. An infected file is marked `infected`, its original is deleted, and an audit entry is written. A clean result is committed at once, so retries don't rescan.
- Scanning is required (`VEY_SCAN_REQUIRED=true`). Without a reachable scanner, uploads wait. Switching it off is an explicit setting, and such documents show `skipped` ("not scanned").
- `python-multipart` (0.0.32) added for FastAPI file uploads.

## Permissions on documents

- Upload sources need at least one reader group or person. Every chunk carries the principals (`user:<id>`, `group:<id>`).
- Changing a source's readers queues an ACL sync that rewrites the payloads of every chunk. Retrieval additionally re-checks each hit against the document's ACL and status in PostgreSQL, so revocation and deletion take effect at query time, not when the sync finishes (implemented with the `fast_rag` graph).

## Chatbot setup before the admin screens

`/v1/admin/chatbots` (create, draft spec, publish, rollback, sources, data rules, access) and `/v1/admin/sources` (upload sources, documents, jobs) are the backend of the Phase 2-4 screens.

- Creating a chatbot needs `admin_area:chatbots#editor`. The creator becomes owner in OpenFGA. Per-chatbot actions check the chatbot's relations (`can_edit_draft`, `can_publish`, `can_manage_access`, `can_view_admin`).
- Saving a draft checks that every provider reference exists, is enabled and has the right capability. Semantic chunking is refused until Phase 2.
- **Publishing is refused while the spec uses an external provider that the chatbot's data rule does not allow.** Data rules are edited by `admin_area:governance#editor` (security reviewers), not by chatbot owners.
- Pipeline versions are immutable once published. Publishing archives the previous live version and starts a new draft. Rollback makes an earlier published version live again. Each step is audited.

## Known limits

- Replacing a document's chunks is delete-then-upsert, so for a moment a search can find no chunks of that document.
- Chunks of profiles no chatbot uses any more are invisible to search but not yet deleted; cleanup arrives with the Pipelines pages.
- Fixed-size chunking counts tokens approximately (words × 1.3).
- Connectors other than upload (SharePoint first) are added once tested against a live tenant.
