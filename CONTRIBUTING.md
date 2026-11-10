# Contributing to Veyntora

Thanks for helping. This page covers how to set up, what a change needs, and how it gets merged. By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before you start

- **Bugs and small fixes:** open a pull request, or an issue first if you're unsure.
- **Larger changes** (a new connector, provider, screen or service): open an issue to agree on the approach first. Decisions that shape the product are written down as an [ADR](docs/decisions/README.md); add one with your change.
- **Security problems:** don't open an issue. See [SECURITY.md](SECURITY.md).

## Set up

You need Docker with Compose v2.20+, `make`, uv 0.13, Python 3.12, Node 24 and pnpm 12.

```bash
make sync              # Python and JS dependencies from the lock files
make env-ci && make up # a local stack with throwaway services (see docs/installation.md)
```

More in [docs/runbooks/local-dev.md](docs/runbooks/local-dev.md).

## Make a change

- **Keep to the existing style.** Ruff, mypy `--strict`, ESLint and Prettier settings are in the repository; match the naming and comment style of the code around yours.
- **Tests come with the change.**
  - Python: `pytest`, next to the code in `services/*/tests` and `packages/*/tests`.
  - Web: Vitest for logic, Playwright (`apps/web/e2e`) for screens.
- **Generated files:** after changing API models or the pipeline spec, run `make gen` and commit the result. CI checks this (`make check-gen`).
- **Database:** a schema change is a new Alembic migration in `services/api/alembic/versions`. Also set `SCHEMA_HEAD` in `services/api/src/veyntora_api/db/schema.py` to its revision; a test checks it.
- **Texts in the UI** go into `apps/web/messages/en.json` and `de.json`, both languages. German uses "Sie".
- **New dependencies** need a reason in the pull request. Prefer what the project already uses.

## Rules the product keeps

- **Secrets are write-only.** Keys go to OpenBao and are never returned by an API, a log or a trace; the UI shows the last 4 characters.
- **Grounded or silent.** Answers come from documents the person may read, with sources, or say they found nothing.
- **Permissions are checked on every request** (OpenFGA), never only in the UI.
- **Nothing writes without approval.** Agent tools that change data wait for a person.
- **Configuration lives in PostgreSQL** and is changed in the admin console, not in code.
- **No demo data.** Screens show real data or an empty state.

## Check before you push

```bash
make ci     # lint, types, unit and database tests, OpenFGA model tests
make e2e    # Playwright against a running stack (make up)
```

Some end-to-end tests create and delete chatbots, sources and users. Run them against a test stack, not an installation with real data.

## Pull requests

- One topic per pull request, with a short description of what changes and why.
- CI must pass. A maintainer reviews and merges.
- By contributing, you agree that your contribution is licensed under the [Apache License 2.0](LICENSE).
