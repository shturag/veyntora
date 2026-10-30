# Veyntora

Self-hosted enterprise knowledge platform. Employees ask questions and get answers with sources, or hand an agent a task that it carries out with their approval. Admins configure every step in a web console.

> Status: **Phase 0 · Foundation**. Sign-in, permissions, secrets, the data model, the audit log and every screen's route are in place. Answering starts in Phase 1.

## Quick start

```bash
docker compose up -d --build
open http://localhost:3000        # admin / dev-admin  or  employee / dev-employee
```

Give Docker at least 16 GB of memory. More in [docs/runbooks/local-dev.md](docs/runbooks/local-dev.md).

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
| `docs` | ADRs, runbooks, API reference, prototype differences |

## Development

`make help` lists the commands. `make ci` runs what CI runs before images are built.

Proprietary. See [LICENSE](LICENSE).
