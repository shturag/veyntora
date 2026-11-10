#!/usr/bin/env bash
# End-to-end tests on their own throwaway stack: compose project veyntora-e2e with its own
# data, secrets and ports (shifted by E2E_PORT_OFFSET, default 10000), so the tests that
# save data never touch the install you use. Removed afterwards; KEEP=1 keeps it.
#
# Usage: scripts/e2e-stack.sh [playwright arguments]
set -euo pipefail

cd "$(dirname "$0")/.."
project=veyntora-e2e
env=.env.e2e
off=${E2E_PORT_OFFSET:-10000}
web=$((3000 + off)) kc=$((8080 + off))
compose=(docker compose -p "$project" --env-file "$env"
  -f deploy/compose/compose.yaml -f deploy/compose/ci-infra.yaml)

cleanup() {
  if [[ "${KEEP:-}" != 1 ]]; then
    "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    rm -f "$env"
  else
    echo "Kept: http://localhost:$web (remove with: ${compose[*]} down -v)"
  fi
}
trap cleanup EXIT

rm -f "$env"
scripts/ci-env.sh "$env" >/dev/null
# This stack's own addresses, replacing the defaults ci-env.sh wrote.
set_var() {
  grep -v "^$1=" "$env" > "$env.tmp" || true
  echo "$1=$2" >> "$env.tmp" && mv "$env.tmp" "$env" && chmod 600 "$env"
}
set_var COMPOSE_FILE ""
set_var VEY_WEB_PORT "$web"
set_var VEY_API_PORT $((8000 + off))
set_var VEY_GRAPHS_PORT $((2026 + off))
set_var VEY_CHANNELS_PORT $((8010 + off))
set_var VEY_PG_PORT $((5432 + off))
set_var VEY_OPENBAO_PORT $((8200 + off))
set_var VEY_KEYCLOAK_PORT "$kc"
set_var VEY_PUBLIC_BASE_URL "http://localhost:$web"
set_var VEY_OIDC_ISSUER "http://localhost:$kc/realms/veyntora"
set_var VEY_IT_OPENBAO_URL "http://localhost:$((8200 + off))"
set_var VEY_OPENBAO_API_TOKEN_VOLUME "${project}_openbao-api-token"
set_var VEY_OPENBAO_RUNTIME_TOKEN_VOLUME "${project}_openbao-runtime-token"

echo "Starting $project on http://localhost:$web ..."
# Health checks can time out while images build on a busy machine: one more try.
"${compose[@]}" up -d --build --wait web graphs workers scheduler ||
  "${compose[@]}" up -d --wait web graphs workers scheduler

# Healthy containers can still be bootstrapping (migrations, Keycloak sync): wait until the
# sign-in page offers sign-in rather than the Setup page.
for _ in $(seq 1 120); do
  curl -sf "http://localhost:$web/sign-in" | grep -q "Sign in with company account" && break
  sleep 5
done
curl -sf "http://localhost:$web/sign-in" | grep -q "Sign in with company account" || {
  echo "The stack did not finish setting up; its logs: ${compose[*]} logs" >&2
  exit 1
}

set -a
# shellcheck disable=SC1090
source "$env"
set +a
export E2E_BASE_URL="http://localhost:$web" E2E_AUTH_DIR="e2e/.auth-e2e"
pnpm --filter @veyntora/web exec playwright test "$@"
