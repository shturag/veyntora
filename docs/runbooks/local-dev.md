# Local development

## Requirements

- Docker Desktop (or Docker Engine) with Compose v2.20+. Veyntora's own services need about 4 GB of memory.
- The services Veyntora runs on, hosted by you (ADR 0033). Two groups:
  - **On the Setup page** at first start, later **Admin → Infrastructure** (ADR 0034): PostgreSQL 16, Valkey, S3, OpenBao, OpenFGA and Keycloak. What each needs: [infrastructure.md](infrastructure.md).
  - **In the admin console:** models, vector store, parser, guardrails, web search and the code sandbox (**Providers & keys**); the virus scanner, Langfuse and Grafana (**Integrations**); email (**Channels & API → Email**).
- For working on the code: uv 0.13, Python 3.12 (`uv python install 3.12`), Node 24, pnpm 12.

## Start

```bash
make env          # .env with the config keys (keep a copy safe)
make up           # builds and starts Veyntora's own services
make setup-code   # the code the Setup page asks for
```

Then open http://localhost:3000. It shows the Setup page until the six services are set up.

**No services of your own yet?** `make env-ci` writes an `.env` for throwaway copies of all of them (`deploy/compose/ci-infra.yaml`, what CI uses), with their settings in the environment, so there is no Setup page. Then `make up` starts those as well. They're for trying Veyntora and for tests, not for real use.

| URL | What |
|---|---|
| http://localhost:3000 | Veyntora (landing, chat, admin console); sign in with a user of your Keycloak realm |
| http://localhost:8000/docs | API (OpenAPI UI) |

Inside the containers, a service on your own machine is at `http://host.docker.internal:<port>`. For your own Prometheus and Grafana, `deploy/observability/` has the scrape jobs and a dashboard.

## What starts

Every container runs its service through `veyntora-api launch`, which starts it with the settings from the Setup page and restarts it when they change. First **`migrate`**, which runs `veyntora-api bootstrap` against your services (once per version of the settings): Alembic, the OpenFGA store, model and bootstrap tuples, the S3 bucket, a Keycloak sync, and the admin grant for `/platform-admins`. Then `api`, `workers`, `scheduler`, `graphs`, `channels`, `web`.

On first start, `bootstrap` imports the virus scanner, Langfuse and Grafana into **Admin → Integrations** when `VEY_CLAMAV_ADDRESS`, `VEY_LANGFUSE_URL` or `VEY_GRAFANA_URL` (and their keys) are set in `.env`. Afterwards they're changed in the console. Grafana dashboards on Monitoring also need a service-account token stored there.

**Uploads wait** until a virus scanner is set up (**Integrations → Virus scanner**), unless `VEY_SCAN_REQUIRED=false`.

**Presidio** is not part of the stack. To find names and places with your own Presidio analyzer, add it under **Providers & keys → Add provider → Guardrail → Presidio** (its base URL, and a key only if a gateway needs one). Then choose it as the **PII provider** on a chatbot's Guardrails page (ADR 0026).

`channels` (Teams and Slack, port 8010) also posts automations' messages and approval cards. Email goes through the SMTP server set under **Channels & API → Email**, for example your own Mailpit while testing.

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
- **ClamAV keeps restarting with exit 137:** raise Docker Desktop memory.
- **Uploads stay "pending":** check `docker compose ps clamav`, and the parser and embedding providers under Providers & keys (Test connection). ClamAV downloads signatures on first start (a few minutes); jobs retry with backoff, see `GET /v1/admin/sources/{id}/jobs`. Only on a machine that cannot run ClamAV, set `VEY_SCAN_REQUIRED=false` in `.env`; documents then show "not scanned".
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

Answers are traced in the Langfuse set up under **Admin → Integrations** (see [external-services.md](external-services.md)). The trace id is stored with each answer; without Langfuse, answers are not traced.

## Writing an MCP tool for Veyntora

A tool that answers questions (a website or wiki search) belongs under **Pipeline → Retrieval → Knowledge tools**: it is then searched with every question (ADR 0035). Tools that do things (tickets, bookings) go to the agent under **Pipeline → Agent → Tools**.

- **One result per page.** Return one embedded resource per page or passage, with its address as `uri` and its title in `_meta.title`. Each becomes a numbered source with "Open page"; one long text block is one source.
- **The question as one input.** A knowledge tool takes the question in its only required text input, or in `query`.
- **Say when to use it.** The description is what the agent reads: "Use it for questions about …". Don't write instructions to the model there; the review page flags them.
- **Mark what it does.** `read_only_hint=True` for tools that only read; `destructive_hint=True` for tools that delete. Without a read-only hint a tool is treated as a write and always needs an approval.
- **Keep results short.** At most 6,000 characters per call reach the model; send the passages that match, not whole pages.
- **No `[n]` in the text.** Veyntora numbers the sources; numbers in brackets inside a page read as citations.

After changing a description or its inputs, use **Discover again**: the tool is switched off until it is reviewed.

## Tools that act as the person (delegated MCP auth)

A server registered with "Pass the user's token through" gets, for each call, a token exchanged from the asking person's Veyntora sign-in (Keycloak standard token exchange, ADR 0021). The dev realm enables standard token exchange on the `veyntora` client. For each such tool:

1. In Keycloak, create a client for the tool (for example `mcp-hr`); the tool validates tokens with this audience.
2. Make the audience available to `veyntora`: under **Clients → veyntora → Client scopes → veyntora-dedicated**, add an *Audience* mapper with *Included Client Audience* `mcp-hr` (access token only).
3. Register the server in Veyntora with authentication *Pass the user's token through* and audience `mcp-hr`.

Without step 2 the exchange is refused and the tool tells the person that an admin must allow its audience. Automations and app keys never get these tools; Teams and Slack users only while they are signed in to Veyntora on the web.
