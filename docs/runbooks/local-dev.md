# Local development

## Requirements

- Docker Desktop (or Docker Engine) with Compose v2.20+. Give it **at least 16 GB of memory**. No model servers run locally: embeddings, reranking and the LLM use provider APIs whose keys you add under Admin → Providers & keys. To run TEI anyway: `docker compose --profile local-models up -d` and set `VEY_TEI_EMBED_URL`/`VEY_TEI_RERANK_URL` (needs about 11 GB more).
- For working on the code: uv 0.13, Python 3.12 (`uv python install 3.12`), Node 24, pnpm 12.

## Start

```bash
make env          # optional: random secrets in .env (otherwise dev defaults are used)
docker compose up -d --build     # or: make up
```

The first start downloads the BGE-M3 and reranker models (about 4 GB) into named volumes.

| URL | What | Sign-in |
|---|---|---|
| http://localhost:3000 | Veyntora (landing, chat, admin console) | `admin` / `dev-admin` (platform admin), `employee` / `dev-employee` |
| http://localhost:8080 | Keycloak admin | `kcadmin` / `dev-keycloak-admin` |
| http://localhost:3001 | Langfuse | `admin@veyntora.local` / `dev-langfuse-admin` |
| http://localhost:3003 | Grafana | `admin` / `dev-grafana-admin` |
| http://localhost:8000/docs | API (OpenAPI UI) | — |

With a generated `.env`, the passwords are the values in that file.

## What starts

Order: `postgres`, `valkey`, `seaweedfs` → `seaweedfs-init` (buckets), `openbao` → `openbao-init` (unseal, policies, tokens), `keycloak` (imports the dev realm), `openfga-migrate` → `openfga` → **`migrate`**. That last job runs `veyntora-api bootstrap`: Alembic, the OpenFGA store, model and bootstrap tuples, the S3 bucket, a Keycloak sync, and the admin grant for `/platform-admins`. Then `api`, `workers`, `scheduler`, `graphs`, `web`.

Model and observability services start alongside: `tei-embed`, `tei-rerank`, `docling`, `litellm`, `langfuse` (+ `clickhouse`, `langfuse-worker`), `otel-collector`, `prometheus`, `loki`, `grafana`. `vllm` needs `--profile gpu` and `VLLM_MODEL`.

`channels` (Teams and Slack, port 8010) also posts automations' messages and approval cards. `mailpit` catches email locally: under **Channels & API → Email** set host `mailpit`, port `1025`, security *None*, any from address, and read the mails at http://localhost:8025.

## Everyday commands

```bash
make sync          # install Python + JS deps
make ci            # lint, types, unit + DB tests, FGA model tests
make e2e           # Playwright against the running stack
make test-integration   # OpenBao write-only policy against the running stack
make gen           # regenerate OpenAPI, TS client, spec schema/TS, FGA JSON
make logs          # follow application logs
make reset         # delete all local data (asks first)
```

Run the web app outside Docker against the compose API: `API_INTERNAL_URL=http://localhost:8000 pnpm --filter @veyntora/web dev`.

## Troubleshooting

- **`ModuleNotFoundError: veyntora_*` on macOS:** uv marks `.venv` hidden and Python 3.12 skips hidden `.pth` files. Use the Makefile targets (they set `PYTHONPATH`), or run `chflags -R nohidden .venv`.
- **TEI, Docling or Langfuse keep restarting with exit 137:** raise Docker Desktop memory to 16 GB or more.
- **Uploads stay "pending":** check `docker compose ps clamav tei-embed docling`. ClamAV downloads signatures on first start (a few minutes); jobs retry with backoff, see `GET /v1/admin/sources/{id}/jobs`. Only on a machine that cannot run ClamAV, set `VEY_SCAN_REQUIRED=false` in `.env`; documents then show "not scanned".
- **`remaining connection slots are reserved`:** the dev Postgres allows 300 connections. Check `pg_stat_activity` for a service with a runaway pool.
- **Start from scratch:** `make reset && make up`.

## Phase 1 evaluation

After adding providers under Admin → Providers & keys (parser, embedding, vector store, LLM, optionally a reranker), take their ids from the Providers page and run:

```bash
docker compose run --rm -v ./evals:/evals:ro workers veyntora-eval /evals/phase1 \
  --parser <id> --embedding <id> --store <id> --llm <id> [--reranker <id>]
```

It prints PASS/FAIL per question and a summary (citations, no-answer, permission leak count, p95 latency), and cleans up after itself.

## Traces

Answers are traced in Langfuse at http://localhost:3001 (sign in as `admin@veyntora.local`; the password is `VEY_LANGFUSE_ADMIN_PASSWORD` from `.env`). The trace id is stored with each answer.
