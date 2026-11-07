<p align="center"><img src="apps/web/public/brand/veyntora-logo.png" alt="Veyntora" width="360"></p>

# Veyntora

Self-hosted enterprise knowledge platform. Employees ask questions and get answers with sources, or hand an agent a task that it carries out with their approval. Admins configure every step in a web console.

> Status: **Phase 0 · Foundation**. Sign-in, permissions, secrets, the data model, the audit log and every screen's route are in place. Answering starts in Phase 1.

## Quick start

```bash
make env                          # .env with the config keys
make up                           # builds and starts Veyntora's own services
make setup-code                   # the code for the Setup page
open http://localhost:3000        # set up PostgreSQL, Valkey, S3, OpenBao, OpenFGA, Keycloak
```

No services of your own yet? `make env-ci && make up` starts throwaway copies too. More in [docs/runbooks/local-dev.md](docs/runbooks/local-dev.md) and [docs/runbooks/external-services.md](docs/runbooks/external-services.md).

## Layout

| Path | What |
|---|---|
| `apps/web` | Next.js app: landing, user app, admin console |
| `services/api` | FastAPI: auth (BFF), OpenFGA checks, config, audit, status |
| `services/graphs` | LangGraph graphs served by Aegra: `fast_rag`, `agent`, `router` |
| `services/workers` | Celery jobs and beat schedule |
| `packages/spec` | Pipeline spec (Pydantic) and generated TS types |
| `packages/providers` | Provider interfaces, registry, contract tests, secret scrubber |
| `packages/ui` | Design tokens and shared components |
| `mcp-servers` | First-party MCP servers (Phase 3) |
| `deploy/compose` | Local stack |
| `deploy/helm`, `deploy/argocd` | Kubernetes chart, values per environment, app-of-apps |
| `deploy/openfga` | Authorization model, tests, bootstrap mapping |
| `design/prototype` | UI reference (read-only) |
| `docs` | ADRs, runbooks, API reference, prototype differences, [user and admin flows](docs/user-flows.md), [use cases](docs/use-cases.md) |

## Development

`make help` lists the commands. `make ci` runs what CI runs before images are built.

Proprietary. See [LICENSE](LICENSE).
