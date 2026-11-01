# Deploying with Argo CD

For the platform team installing Veyntora on Kubernetes. Local development is in `local-dev.md`.

## What gets deployed

- **Chart:** `deploy/helm/veyntora-service`, one hardened chart per service. Pods run as non-root with a read-only root filesystem, dropped capabilities and a default-deny NetworkPolicy.
- **Values:** `deploy/helm/values/<env>/<service>.yaml` sets the image, command, replicas, allowed callers, secrets, OpenBao role, ingress and backups.
- **Argo CD:** `deploy/argocd/project.yaml` + `root-<env>.yaml` form an app of apps.
  - **dev** syncs automatically. CI points dev at every commit on `main` (job `dev-bump` sets `image.tag` to the commit SHA).
  - **staging** and **prod** sync by hand after approval; a person sets `image.tag`.
- **Migrations:** the `api` release runs `veyntora-api bootstrap` as a **PreSync** hook, connected as the database **owner**. A failing migration stops the sync.

```bash
kubectl apply -n argocd -f deploy/argocd/project.yaml
kubectl apply -n argocd -f deploy/argocd/root-dev.yaml
```

## Prerequisites in the cluster

- **External Secrets Operator**, with a `ClusterSecretStore` named `openbao`.
- **OpenBao Agent Injector**, with Kubernetes auth enabled.
- **cert-manager**, with a `ClusterIssuer` (the values use `letsencrypt`; set yours).
- **ingress-nginx.**
- **External systems you provide:** PostgreSQL 16, an S3-compatible store, Keycloak, OpenFGA, Qdrant, Valkey and Langfuse.

## 1. Database roles

Run once as a database administrator. The services never connect as the owner.

```sql
CREATE ROLE veyntora LOGIN PASSWORD '…';           -- owner: migrations and bootstrap only
CREATE DATABASE veyntora OWNER veyntora;
CREATE ROLE veyntora_runtime LOGIN PASSWORD '…';   -- the services: rows only
GRANT CONNECT ON DATABASE veyntora TO veyntora_runtime;
```

Migration 0020 grants `veyntora_runtime` read and write on rows. It also sets default privileges for later migrations. The runtime role cannot:
- change tables;
- disable the audit triggers;
- truncate or grant;
- write the migration version.

## 2. Secrets (OpenBao → ExternalSecrets)

Infrastructure credentials live in OpenBao at `kv/infra/veyntora`. The External Secrets Operator syncs them into the `veyntora-api-env` and `veyntora-migrate-env` Secrets (see `values/<env>/api.yaml`).

| Property | Used for |
|---|---|
| `runtime_database_url` | services: `postgresql+asyncpg://veyntora_runtime:…@host/veyntora` |
| `owner_database_url` | migrations and backups: `postgresql+asyncpg://veyntora:…@host/veyntora` |
| `oidc_client_secret`, `keycloak_sync_client_secret` | Keycloak clients |
| `s3_access_key`, `s3_secret_key` | object store (documents, audit archive) |
| `langfuse_secret_key` | traces |
| `internal_token_secret` | API → graph server tokens (32+ characters) |

Model keys, connector secrets and people's own keys are never in Kubernetes. The API writes them to OpenBao, and only the runtime role reads them.

## 3. OpenBao Kubernetes auth

```bash
bao auth enable kubernetes
bao write auth/kubernetes/config kubernetes_host="https://$KUBERNETES_SERVICE_HOST"
bao policy write veyntora-api deploy/compose/openbao/api-policy.hcl          # write-only
bao policy write veyntora-runtime deploy/compose/openbao/runtime-policy.hcl  # read
# One namespace per environment (veyntora-dev, veyntora-staging, veyntora-prod).
bao write auth/kubernetes/role/veyntora-api \
  bound_service_account_names=api bound_service_account_namespaces=veyntora-prod \
  policies=veyntora-api ttl=1h
bao write auth/kubernetes/role/veyntora-runtime \
  bound_service_account_names=workers,scheduler,graphs \
  bound_service_account_namespaces=veyntora-prod \
  policies=veyntora-runtime ttl=1h
```

The agent writes the token to `/vault/secrets/token`, and the chart points `VEY_OPENBAO_TOKEN_FILE` there.

## 4. Object store

Create two buckets:
- `veyntora`: document originals.
- `veyntora-audit`: the write-once audit archive. Create it with **Object Lock enabled**; that is only possible when the bucket is created.

Give the runtime credentials list, read and write on both, plus `PutObjectRetention` on the audit bucket. Set `VEY_AUDIT_ARCHIVE_BUCKET=veyntora-audit`. Without it, nothing is archived and audit entries are never removed.

## 5. Ingress and TLS

The `web` release is the only public entry. In `values/<env>/web.yaml`:
- set `ingress.host`;
- cert-manager issues `ingress.tlsSecret`;
- HSTS is on.

The API trusts `X-Forwarded-For` only from `VEY_TRUSTED_PROXIES`. Set it to the pod network the web app runs in; the default in the values is `10.0.0.0/8`.

## 6. Backups and restore

- **Database:**
  - With point-in-time recovery on a managed PostgreSQL, rely on that.
  - Otherwise set `backup.enabled: true` in `values/prod/api.yaml`. A nightly `pg_dump` (custom format) goes to the `veyntora-backups` volume and is kept 14 days. Back up that volume off-cluster.
  - To restore:

    ```bash
    pg_restore --no-owner --dbname "$OWNER_DATABASE_URL" veyntora-<time>.dump
    ```

    Then run `SELECT audit_first_broken_link()`; NULL means the audit chain is intact. Finally sync `api` so migrations and grants are applied.
- **What a database restore does not cover:**
  - Qdrant: rebuildable from the documents (re-index), or snapshot it.
  - OpenBao: take raft snapshots (`bao operator raft snapshot save`).
  - The object store: use its versioning.
- **Checking a restore** locally: `scripts/backup-restore-check.sh` dumps the compose database the same way, restores it into a scratch database, and compares tables, rows and the audit chain.

## 7. Load test

```bash
docker run --rm -i -e BASE=https://veyntora.example.com -e SESSION=<vey_session cookie> \
  -e PROFILE=load grafana/k6:1.3.0 run - < scripts/load/k6-api.js
```

- `smoke` runs 20 users for a minute; `load` runs 200 users for 10 minutes.
- Thresholds: under 1% errors; p95 under 300 ms for public endpoints and under 500 ms for signed-in ones.
- Answer latency is the model's, and is watched in Monitoring.
