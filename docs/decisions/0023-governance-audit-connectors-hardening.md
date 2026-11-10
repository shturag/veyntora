# 0023 · Governance, data subject requests, audit archive, access reviews, Confluence/database/file-share connectors, hardening

Status: accepted · 2026-11-01

## Product owner decisions

- **File shares:** `smbprotocol` 1.17.0 is approved (MIT).
- **Confluence:** both Cloud and Data Center. Permissions come from space permissions and page restrictions; anything unmapped is dropped.
- **Databases:** PostgreSQL (asyncpg, already installed), SQL Server (`python-tds` 1.17.1), MySQL/MariaDB (`aiomysql` 0.3.2) and Oracle (`oracledb` 26.0.1, thin mode). 26.1.0 was newer than two weeks.
- **Audit names:** move to a separate table, so erasure can pseudonymise without breaking the hash chain.
- **Roles:** two new platform roles. *Legal* places and lifts holds; *Data protection officer* approves erasures and exports, and must not be the requester. Platform admins cannot do either.
- **Access reviews:** access nobody reviewed stays. Platform admins are told once and the round shows as overdue.

## Governance

- **Settings** (Governance page) are stored in `platform_settings`, with `extra.governance` holding:
  - retention for chats, traces, uploads and the audit log;
  - masking of traces and admin reviews;
  - masking required before any external provider;
  - external providers allowed only in EU regions;
  - the AI notice;
  - the access-review interval.
- **Enforcement of the platform rules:**
  - Required masking and EU-only are checked when a chatbot's data rule is saved, at publish, and on every run.
  - An EU region is a provider region starting with `eu` or `europe`.
- **The AI notice** appears on sign-in, in the chat footer, and at the start of every new Teams or Slack conversation.
- **Retention:** a nightly purge (workers) removes:
  - chats past the chatbot's or the platform's retention, or after a day for people who turned "Keep chat history" off (chats with a saved answer stay);
  - old uploads;
  - Langfuse traces, through its public API.

  Nothing of a person or chatbot under an active legal hold is purged.
- **Platform roles** other than platform admin are granted to groups on the Governance page by platform admins. Platform admins themselves come from the bootstrap group.

## Data subject requests

- **Steps:**
  1. The request is recorded by a Governance editor or a DPO.
  2. The page shows what is held about the person.
  3. Someone handling the request marks the person's identity as verified.
  4. A DPO who is not the requester approves.
  5. The erasure or export is carried out. A legal hold blocks this step.
- **Erasure:**
  - Chats (with their messages, citations, feedback and hand-offs), saved answers, notifications, channel links and own model keys (in OpenBao) are deleted.
  - Uploads are removed from every index by delete jobs.
  - Eval cases taken from their answers are masked.
  - Usage keeps its numbers without the person.
  - The account is scrubbed and suspended.
  - Audit entries keep the person's id, and their name becomes a pseudonym.
  - The workers delete the Langfuse traces.
- **Access:** the workers build a ZIP (profile, chats, saved answers, feedback, uploads). The same ZIP is "Export my data" in Settings.
- **Report:** canonical JSON, signed with HMAC-SHA256 (`VEY_INTERNAL_TOKEN_SECRET`). Its hash and signature go into the audit log. Downloads of the report and the export are audited.

## Audit log

- **Names outside the chain:** the hash chain covers the actor id. People's names are in `audit_actors`, which erasure pseudonymises. Migration 0017 rewrote existing entries once without names and recomputed the chain; the previous head hash is in an `audit.names_moved` entry.
- **The page:** search, categories, date ranges, change detail (a diff of what was recorded) and the chain check. Export as CSV or JSON lines (with hashes), masked by default; exports are audited.
- **Write-once archive:** nightly batches of JSON lines go to a bucket under S3 Object Lock in compliance mode until the end of the audit retention. Each batch is recorded with its SHA-256 and the chain hash of its last entry.
  - Locally, SeaweedFS 4.51 enforces Object Lock: compose creates the bucket with a lock and grants only list, read, write and `PutObjectRetention`.
  - A test checks that deletes are refused.
- **Retention:**
  - Only archived entries older than the retention (at least 365 days) can be removed, and only inside `audit_trim`. The append-only trigger allows nothing else.
  - The chain is re-anchored at the last removed entry (`audit_anchor`), so verification still covers everything left.
  - Without an archive bucket, nothing is removed.

## Access reviews

- A round snapshots:
  - every chatbot role grant, reviewed by the chatbot's owner;
  - every manual group membership, reviewed by the group's owner.

  Keycloak and rule-based memberships come from their source and are not reviewed. Items without an owner go to platform admins.
- **Revoking** goes through the normal access paths and is audited. A chatbot never loses its last owner this way.
- **Rounds** start every N days (default 90) or by hand. Platform admins close them.
- **Schema:** migration 0019 replaces the core schema's unused per-group placeholder tables.

## Connectors (listing sync)

- **Confluence:** pages via `/rest/api/content` (storage format).
  - Readers are the space's read permissions, narrowed by the read restrictions of the page and of every ancestor. A group or user is kept only if every level lists it and the space lets it read.
  - Space permissions come from `/api/v2/spaces/{id}/permissions` on Cloud and `/rest/api/space/{key}?expand=permissions` on Data Center.
  - Groups map by name, users by e-mail.
  - This is fail-closed: a user allowed only through a group the restriction does not list is dropped.
- **Databases:**
  - One SELECT, checked when saved. It runs in a read-only transaction where the engine has one and is always rolled back.
  - There is a row cap; a listing that hits it counts as incomplete.
  - Readers come from the source, or per row from a column that names a Veyntora group. A value that matches no group means nobody may read the row.
- **File shares:**
  - Each file's DACL is read with SMB2 QUERY_INFO (security, DACL).
  - Readers are the SIDs with an allow entry for reading, minus those with a deny entry; they map through a SID map.
  - smbprotocol is synchronous, so its calls run in a worker thread.
- **The listing sync** takes permissions from the source system when it has them. A permission change on an unchanged document queues a permission sync.
- **Tests:**
  - Confluence against mocked Cloud and Data Center responses (not tested against a live instance).
  - PostgreSQL for real.
  - Samba in a container: listing, DACL, download.
  - SQL Server, MySQL and Oracle are not tested live.

## Hardening

- **Outbound addresses:** `PinnedPublicTransport` resolves an own-model endpoint once per request, refuses private addresses, and connects to exactly the checked address. TLS still verifies the host name (SNI) and the Host header is unchanged.
  - The Anthropic SDK uses its own vendored HTTP client, which cannot take this transport. Own Anthropic models therefore use Anthropic's API only, with no custom endpoint.
- **Forwarded headers:** `X-Forwarded-For` and `-Proto` are trusted only from `VEY_TRUSTED_PROXIES`, through uvicorn's proxy-headers handling; the app uses the connection's resolved client address.
- **Database role:** the services connect as `veyntora_runtime`. It has rows only: no ALTER, TRUNCATE, trigger changes, grants or migration version. The owner runs migrations and bootstrap only.
  - Compose creates the role (`postgres-roles`).
  - Migration 0020 grants rights and sets default privileges.
- **Production:**
  - The chart gains ExternalSecrets, Ingress (cert-manager TLS, HSTS), OpenBao Agent Injector annotations (Kubernetes auth: the API's role writes only, the runtime role reads), a backup CronJob, and an owner-only migration job.
  - CI moves dev to every commit on main.
  - k6 load test and a backup-and-restore check (scripts).
  - Runbook: `docs/runbooks/deploy.md`.

## Open

- Confluence attachments are not read (pages only).
- Langfuse trace deletion uses its public API; it is not tested against a live Langfuse.
- SQL Server, MySQL and Oracle, Confluence, and Kubernetes auth with OpenBao need a live check with real systems.
