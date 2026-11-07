# 0033 · Veyntora runs on infrastructure you host

Status: accepted · 2026-11-06 · Follows ADR 0032 · Where the six services are set: changed by ADR 0034 (the Setup page and Admin → Infrastructure)

## Context

After ADR 0032, compose still started the services Veyntora runs on: PostgreSQL, Valkey, S3 (SeaweedFS), OpenBao, OpenFGA and Keycloak, plus ClamAV, the code sandbox and Mailpit. Installations already run these services, the way they run Qdrant or Docling. A second copy in Veyntora's stack duplicates data and secrets, and it hides which settings Veyntora really depends on.

## Decision

- **Compose has only Veyntora's services:** migrate, api, workers, scheduler, graphs, channels and web.
- **Six services are set in `.env`:** PostgreSQL, Valkey, S3, OpenBao, OpenFGA and Keycloak. Veyntora needs them before the admin console can work: it signs in with Keycloak, authorises with OpenFGA, stores settings in PostgreSQL and keys in OpenBao, and runs sessions and jobs on Valkey. S3 stays in `.env` because moving it at runtime would strand the stored documents.
  - Each address and password is a required setting (`.env.example`).
  - The two OpenBao tokens (write-only for the API, read for the runtime services) are read from the Docker volumes your OpenBao's setup writes. The policies and the setup script are in `deploy/compose/openbao/`.
  - Containers reach services on the same machine at `host.docker.internal`. Compose maps it on Linux too.
- **The rest is set in the admin console.**
  - **Code sandbox:** a provider (**Providers & keys → Code interpreter**), with its token as the key.
  - **Email:** the SMTP relay (**Channels & API → Email**); Mailpit is one.
  - **Virus scanner (new):** a platform setting under **Integrations**, with **Test connection**.
    - Changing it requires editor rights on Data sources, and every change is audited.
    - Uploads and attachments read it from the database; `VEY_CLAMAV_ADDRESS` only seeds it once, like Langfuse and Grafana.
- **CI:** throwaway copies of the services are in `deploy/compose/ci-infra.yaml`. `scripts/ci-env.sh` writes a matching `.env`, and `make env-ci` runs it. They're also how you try Veyntora without your own services, and they're not for real use.

## Consequences

- **Fresh clone:** it needs an `.env` before `make up`, either pointing at your services or written by `make env-ci`.
- **Moving an existing stack:** this installation was moved with its data, by copying four things:
  - the `veyntora` and `aegra` databases (`pg_dump` / `pg_restore --no-owner --role=…`);
  - the OpenFGA database;
  - the `veyntora` Keycloak realm with its users, which keeps user IDs (`kc.sh export` / `import --override`);
  - the KV secrets (latest version of each, copied from OpenBao to OpenBao) and both S3 buckets, keeping audit retention.
- **Uploads:** they wait until a scanner is set up, unless `VEY_SCAN_REQUIRED=false`.
