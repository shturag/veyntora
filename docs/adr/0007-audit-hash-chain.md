# 0007 · Append-only, hash-chained audit log

Status: accepted · 2026-10-30 · Phase 0

## Decision

- `audit_events` is append-only, enforced in the database. Triggers reject `UPDATE`, `DELETE` and `TRUNCATE`.
- A `BEFORE INSERT` trigger takes an advisory lock, assigns `chain_seq` from a sequence and sets `hash = sha256(prev_hash || canonical row text)`. The canonical text covers id, timestamp (microseconds since epoch), actor, action, target, before/after (`jsonb::text`, which is key-ordered), IP, user agent and request id.
- Chain order is `chain_seq`, not `id`: a transaction can take an id and commit after a later one, but `chain_seq` is assigned under the lock.
- `audit_first_broken_link()` verifies the chain in SQL. A test tampers with a row (bypassing the trigger as table owner) and checks it is detected.
- Before/after values are scrubbed of secrets before they are written.
- Requires READ COMMITTED isolation (the PostgreSQL default) so the trigger sees the latest committed row.

## Phase 7

- Periodic export of chain segments with their head hash to a WORM (S3 Object Lock) bucket, so even a database superuser cannot rewrite history unnoticed.
- The application connects as a role that does not own the table, so it cannot disable the triggers.
- GDPR erasure vs. audit retention: the audit log keeps actor ids, not content. How names in old entries are pseudonymised without breaking the chain is an open question for Phase 7.
