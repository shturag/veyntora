# 0004 · Secrets are write-only

Status: accepted · 2026-10-30 · Phase 0

## Decision

- Every key (providers, BYOK, MCP servers, sources, channels) is written to **OpenBao KV v2** under fixed path patterns: `providers/{id}`, `users/{user_id}/{provider}`, `mcp/{id}`, `sources/{id}`, `channels/{id}`. Any other path is refused before a request is sent.
- PostgreSQL stores only `secret_ref`, `secret_last4` (only for values of 12 characters or more) and `secret_expires_at`.
- Write-only is enforced **twice**:
  1. `SecretWriter` has no read method (unit test checks its public surface).
  2. The API's OpenBao token has policy `veyntora-api` with no `read` on `kv/data/*` or `kv/metadata/*` (integration test: write 200, read 403).
- Graphs and workers get a separate token (`veyntora-runtime`) that can read but not write.
- In compose, each token is in its own volume. Only the init job mounts the root token and unseal key.
- A shared scrubber (`veyntora_providers.scrub`) removes secrets by key name and by shape (JWT, Bearer, `sk-…`, Vault tokens, AWS keys, Slack tokens, Veyntora app keys) from logs, audit before/after values and, from Phase 1, Langfuse traces.

## Production

OpenBao runs as a 3-node raft cluster with TLS and auto-unseal. Services authenticate with **Kubernetes auth** bound to their service accounts instead of static tokens. The compose setup (one key share, single-node raft, tokens in volumes) is for local development only.

## Later phases

Rotation with a grace period (`previous_secret_ref`, `previous_secret_valid_until`) and expiry alerts 14 days ahead arrive with Providers (Phase 2).
