# Your own Keycloak, Langfuse and Grafana

None of these is bundled (ADR 0032, ADR 0033): Veyntora connects to the ones you run. The vector store, parser and models are providers, added under **Providers & keys**. How you connect them differs:

| Service | Configured in | Why |
|---|---|---|
| Langfuse | Admin console → **Integrations** | Configuration lives in PostgreSQL, keys in OpenBao (ADR 0024) |
| Grafana | Admin console → **Integrations** | Same |
| Keycloak | The Setup page, then **Admin → Infrastructure** (ADR 0034); Helm values | You need Keycloak to sign in to the admin console, so it is set before (Setup page) |

## Langfuse

1. In Langfuse, open the project, then **Settings → API keys**, and create a key pair.
2. In Veyntora, open **Admin → Integrations → Langfuse** and fill in:
   - **Address**: the URL Veyntora's services use to reach Langfuse.
   - **Address for browsers** (optional): the URL people use, if it is different. "Open trace" links use it.
   - **Public key**.
   - **Where it runs**: self-hosted or external.
3. Store the **secret key**. It goes straight to OpenBao and is never shown again; the page shows only its last 4 characters.
4. Click **Test connection**. A worker calls Langfuse with the stored key and shows the result after a few seconds.

New answers are traced within a minute, with no restart.

**External Langfuse** (for example Langfuse Cloud): traces contain questions and answers, so sending them there is data egress. A chatbot's traces go there only when its data rule allows it: **Chatbot → Access → Data rule → Send traces to an external Langfuse**. Personal data in those traces is always masked. The Governance page lists the chatbots that allow it.

To set it up from `.env` instead, `veyntora-api bootstrap` reads `VEY_LANGFUSE_URL`, `VEY_LANGFUSE_PUBLIC_KEY` and `VEY_LANGFUSE_SECRET_KEY` and imports them once, but only when Langfuse is not set up yet. After that, changing those variables does nothing; make changes in the console. They are empty by default, so nothing is imported.

Only answers are traced. The services do not send their own spans anywhere.

## Grafana

1. In Grafana, create the service account under **Administration → Users and access → Service accounts**:
   - give it the **Viewer** role;
   - add a token (`glsa_…`);
   - share with it the dashboards Veyntora should show.
2. In Veyntora, open **Admin → Integrations → Grafana**:
   - enter the address (and, if different, the address for browsers);
   - store the token;
   - click **Test connection**.
3. Under **Dashboards on Monitoring**, search and choose up to 12 dashboards.

The Monitoring page draws those dashboards with its own charts:

| Grafana panel type | Shown on Monitoring as |
|---|---|
| Time series | Lines |
| Stat, gauge | Numbers |
| Table | A table |
| Anything else | A link to Grafana |

How the data is read:
- Veyntora reads the data through Grafana's API. The graph server holds the token, because the API can only write secrets, never read them.
- Nobody needs a Grafana login, and nothing is embedded in a frame.
- Only the dashboards chosen here can be read through Veyntora.
- People who may view Monitoring see them; only people who may edit Monitoring can search for more.
- Template variables use their current saved values.

## Keycloak

Veyntora needs two clients in a realm:

| Client | Kind | Needs |
|---|---|---|
| `veyntora` | Confidential, standard flow with PKCE (S256) | Redirect URI `<public URL>/api/auth/callback`. Post-logout redirect `<public URL>/*`. Standard token exchange on. Mappers: audience `veyntora-api`, `groups` (full path), `locale` |
| `veyntora-sync` | Confidential, service accounts only | Service-account roles `realm-management`: `view-users`, `query-users`, `query-groups` |

### 1. Create the realm

`scripts/keycloak-realm.py` writes the realm from the bundled one, without the development users. Its client secrets come from your environment:

```bash
VEY_PUBLIC_BASE_URL=https://veyntora.example.com \
VEY_OIDC_CLIENT_SECRET="$(openssl rand -hex 24)" \
VEY_KEYCLOAK_SYNC_CLIENT_SECRET="$(openssl rand -hex 24)" \
scripts/keycloak-realm.py --realm veyntora --out veyntora-realm.json
```

Then import the file into Keycloak:
- **New realm:** open **Create realm** and choose the file under **Resource file**.
- **Existing realm:** open **Realm settings**, choose **Action → Partial import**, and import the clients (and the groups, unless you add `--without-groups`).

The file contains the two secrets. Delete it after the import.

### 2. Point Veyntora at it

Compose: enter them on the Setup page (first start) or in **Admin → Infrastructure → Keycloak**: the issuer (exactly the "issuer" Keycloak reports), the address for the containers if different, and the two clients' secrets. The platform admin group stays `VEY_BOOTSTRAP_ADMIN_GROUP` in `.env` (default `/platform-admins`).

With settings from the environment (CI), these are the variables:

```bash
VEY_OIDC_ISSUER=https://sso.example.com/realms/veyntora          # exactly the "issuer" Keycloak reports
VEY_OIDC_INTERNAL_BASE=https://sso.example.com/realms/veyntora   # how the services reach it; often the same
VEY_OIDC_CLIENT_SECRET=...           # the veyntora client's secret
VEY_KEYCLOAK_SYNC_CLIENT_SECRET=...  # the veyntora-sync client's secret
VEY_BOOTSTRAP_ADMIN_GROUP=/platform-admins   # the group whose members become platform admins
```

Helm: put `VEY_OIDC_ISSUER`, `VEY_OIDC_INTERNAL_BASE` and `VEY_BOOTSTRAP_ADMIN_GROUP` under `env:` in the values of `api`, `graphs`, `workers` and `scheduler`. The two client secrets come from OpenBao (`infra/veyntora`: `oidc_client_secret`, `keycloak_sync_client_secret`) through the existing `externalSecrets`.

### 3. Check

```bash
docker compose run --rm migrate veyntora-api check-identity
```

The check names whatever is wrong:
- an issuer that does not match `VEY_OIDC_ISSUER`;
- a sync client that cannot sign in;
- missing service-account roles.

`bootstrap` runs the same check and stops with the same message, so a mistake does not turn into a 401 later on.

Users and groups come from Keycloak's admin API, so the provider must be Keycloak. Other OIDC providers (Entra ID, Okta) can be connected to that Keycloak as identity providers.
