# Veyntora developer commands. `make help` lists them.

SHELL := /bin/bash
ROOT := $(abspath .)
UV ?= uv
PNPM ?= pnpm
# Explicit import paths so local runs never depend on editable-install .pth files
# (macOS can flag them hidden; see docs/runbooks/local-dev.md).
export PYTHONPATH := $(ROOT)/packages/spec/src:$(ROOT)/packages/providers/src:$(ROOT)/services/api/src:$(ROOT)/services/graphs/src:$(ROOT)/services/workers/src:$(ROOT)/services/channels/src
# Dev user passwords for Playwright when .env exists (scripts/gen-env.sh).
ifneq (,$(wildcard .env))
include .env
export VEY_DEV_ADMIN_PASSWORD VEY_DEV_EMPLOYEE_PASSWORD
endif
FGA_CLI := docker run --rm -v $(ROOT)/deploy/openfga:/w -w /w openfga/cli:v0.8.2

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------ setup

.PHONY: sync
sync: ## Install Python and JS dependencies from the lock files
	$(UV) sync --all-packages --frozen
	@if [ "$$(uname)" = "Darwin" ]; then chflags -R nohidden .venv; fi
	$(PNPM) install --frozen-lockfile

.PHONY: env
env: ## Create .env with random secrets (keeps an existing .env)
	@scripts/gen-env.sh

# ------------------------------------------------------------------ stack

.PHONY: up
up: env ## Build and start the whole local stack
	docker compose up -d --build
	@echo "Web: http://localhost:3000  Keycloak: http://localhost:8080  Langfuse: http://localhost:3001  Grafana: http://localhost:3003"

.PHONY: down
down: ## Stop the stack (keeps data)
	docker compose down

.PHONY: reset
reset: ## Stop the stack and delete all local data volumes
	@read -p "Delete all local Veyntora data (volumes)? [y/N] " ok && [ "$$ok" = "y" ]
	docker compose down -v

.PHONY: ps
ps: ## Service status
	docker compose ps -a

.PHONY: logs
logs: ## Follow logs of the application services
	docker compose logs -f api web graphs workers scheduler migrate

# ------------------------------------------------------------------ code generation

.PHONY: gen
gen: ## Regenerate OpenAPI, the TS API client types, the spec JSON Schema/TS and the FGA model JSON
	$(UV) run --no-sync veyntora-api openapi docs/api/openapi.json
	$(PNPM) --filter @veyntora/web gen:api
	$(PNPM) --filter @veyntora/spec gen
	$(FGA_CLI) model transform --file model.fga > deploy/openfga/model.json

.PHONY: check-gen
check-gen: gen ## Fail if generated files are out of date
	git diff --exit-code -- docs/api/openapi.json apps/web/src/lib/api/schema.d.ts packages/spec/ts packages/spec/schema deploy/openfga/model.json

# ------------------------------------------------------------------ quality

.PHONY: lint
lint: ## Ruff, ESLint, Prettier check
	$(UV) run --no-sync ruff check packages services
	$(UV) run --no-sync ruff format --check packages services
	$(PNPM) --filter @veyntora/web lint

.PHONY: typecheck
typecheck: ## mypy --strict and tsc
	$(UV) run --no-sync mypy packages/spec/src packages/providers/src services/api/src services/graphs/src services/workers/src services/channels/src
	$(PNPM) -r typecheck

.PHONY: test
test: ## Unit and database tests (starts a throwaway Postgres via testcontainers)
	$(UV) run --no-sync pytest -q
	$(PNPM) --filter @veyntora/web test

.PHONY: fga-test
fga-test: ## OpenFGA model tests
	$(FGA_CLI) model test --tests model.tests.fga.yaml

.PHONY: test-integration
test-integration: ## Tests against the running stack (secrets policy)
	VEY_IT_OPENBAO_API_TOKEN=$$(docker run --rm -v veyntora_openbao-api-token:/t:ro alpine:3.22 cat /t/api.token) \
	VEY_IT_OPENBAO_RUNTIME_TOKEN=$$(docker run --rm -v veyntora_openbao-runtime-token:/t:ro alpine:3.22 cat /t/runtime.token) \
	$(UV) run --no-sync pytest -q services/api/tests/integration

.PHONY: e2e
e2e: ## Playwright end-to-end tests against the running stack
	$(PNPM) --filter @veyntora/web exec playwright test

.PHONY: ci
ci: lint typecheck test fga-test ## Everything CI runs before building images

.PHONY: docs-flows
docs-flows: ## Redraw the flowcharts in docs/flows from docs/flows/diagrams.py
	$(UV) run --no-sync python docs/flows/diagrams.py
