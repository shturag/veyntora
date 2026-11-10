# 0024 · Langfuse and Grafana as configuration, your own Keycloak

Status: accepted · 2026-11-02

## Product owner decisions

- **Langfuse and Grafana** are set up in the admin console (**Integrations**), not in deployment files. Their keys follow ADR 0004: write-only in OpenBao, with the last 4 characters and the expiry shown.
- **Keycloak** stays deployment configuration. People sign in through it, so it cannot be set up from behind the sign-in. A runbook and a startup check replace a UI.
- **Grafana dashboards** are shown on the Monitoring page through Grafana's API, using a service-account token.
- **The bundled services stay the default** in compose. Any of them can be left out.

## Integrations

- **Storage:**
  - One row per kind in `integrations` (`langfuse`, `grafana`), written through ConfigService: audited, versioned, with an outbox event.
  - The key is at `kv/integrations/{kind}`; the API's path allow-list now includes it.
  - Replacing a key destroys the old version at once. Nothing depends on it during a hand-over, unlike model providers.
- **Who uses the key.** The API never reads a key, so it never uses one:
  - **Graphs:** the Langfuse tracer, re-resolved at most once a minute, so a change needs no restart.
  - **Graphs:** the Grafana reads for Monitoring, at `/integrations/grafana/*`, an Aegra custom route.
  - **Workers:** "Test connection", the retention purge, and the deletion of a person's traces for a data subject request.
- **Grafana reads:**
  - The API forwards the caller's Keycloak token, and the graph server checks `admin_area:monitoring` itself: viewer to read, editor to search.
  - Only dashboards chosen in Integrations can be read.
  - Panels come back as data:
    - time series become lines;
    - stat and gauge become numbers;
    - tables become tables;
    - other types become a link.
  - Monitoring draws them with its own charts. No iframe means no Grafana login, no `allow_embedding` and no third-party cookies.
- **External Langfuse is data egress:**
  - Langfuse has a hosting setting, like providers.
  - When it is external, a chatbot's traces go there only if its data rule has `allow_external_traces`. Personal data is always masked there.
  - The chatbot Access page now edits the whole data rule. Several screens already pointed there, but before this there was no editor in the web app.
- **Seed:**
  - `bootstrap` imports `VEY_LANGFUSE_*` and `VEY_GRAFANA_URL` once, but only when nothing is set up. The bundled compose stack therefore traces from the first start.
  - From then on, the database is the source of truth.
  - In Helm, the unused `VEY_LANGFUSE_SECRET_KEY` on the API is removed.

## Bundled or your own

- **Compose profiles** `bundled-keycloak`, `bundled-langfuse` and `bundled-grafana`:
  - `make env` writes all three into `COMPOSE_PROFILES`, and adds them to an older `.env`.
  - The dependencies on Keycloak are `required: false`.
- **Keycloak:**
  - The issuer, the back-channel URL and the admin group are environment variables.
  - `scripts/keycloak-realm.py` writes the realm for another Keycloak, without the development users.
  - `veyntora-api check-identity`, also run by `bootstrap`, reports these problems in words:
    - an issuer that does not match;
    - a sync client that cannot sign in;
    - missing `realm-management` roles.
- **The OTel collector** still sends the services' own spans (never answers) to `VEY_OTLP_TRACES_ENDPOINT`, which is the bundled Langfuse by default.

## Not done

- **Other OIDC providers directly:** user and group sync and token exchange use Keycloak's APIs. Entra ID or Okta connect to Keycloak as identity providers.
- **Grafana panel types beyond time series, stat, gauge and table:** they link to Grafana.
