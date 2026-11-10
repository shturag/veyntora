# 0008 · One write path for configuration

Status: accepted · 2026-10-30

## Decision

`veyntora_api.core.config_service.ConfigService` is the only way configuration rows change. In the caller's transaction it:

1. validates the change (Pydantic input models; unknown or protected fields are refused),
2. bumps the row's `version` and rejects stale writes (`expected_version`, `409 Conflict`),
3. writes an audit entry with before/after values, actor, IP, user agent and request id,
4. writes an `outbox_events` row (topic `<entity>.<action>`).

A worker job (`veyntora.relay_outbox`, every 10 s) publishes outbox rows with `NOTIFY veyntora_config` so graphs, workers and the scheduler can reload.

Pipeline specs are versioned as whole documents (`pipeline_versions`). Other config rows keep their history in the audit log; one-click rollback (ADR 0022, 0023) re-applies an audit entry's `before` through the same service.

## Why an outbox

The event is committed atomically with the change. No event without a change, no change without an event.
