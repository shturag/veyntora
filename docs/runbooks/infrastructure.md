# The services Veyntora runs on

PostgreSQL 16, Valkey, S3, OpenBao, OpenFGA and Keycloak are set up in the browser (ADR 0034): on the **Setup page** at first start, and in **Admin → Infrastructure** later. This runbook covers what each one needs, what to do when starting fails, and how to move one.

## Before the first start

```bash
make env   # .env with the config keys; keep a copy safe
make up    # Veyntora's services; the web app opens on the Setup page
make setup-code
```

Open http://localhost:3000, enter the setup code, then fill in each service. **Test connection** checks each one the way Veyntora will use it.

Inside the containers, a service on the same machine is at `host.docker.internal:<port>`.

| Service | What it needs |
|---|---|
| PostgreSQL 16 | Three roles and two databases:<ul><li>`veyntora` owns database `veyntora`;</li><li>`veyntora_runtime` has CONNECT on it (rows are granted by migration 0020);</li><li>`aegra` owns database `aegra`.</li></ul>See `deploy/compose/postgres/init.sh` and docs/runbooks/deploy.md, "Database roles". |
| Valkey or Redis | Database 0 for Veyntora and 2 for the graph server (both can be changed). A password is optional. |
| S3 | An access key that can use both buckets. Missing buckets are created; the audit bucket gets Object Lock, which the store must allow. |
| OpenBao | A KV v2 engine (default `kv/`). An **admin token** that may write policies and create tokens, used once and not stored. Veyntora writes the policies `veyntora-api`, `veyntora-runtime` and `veyntora-infra-read` and issues a token for each. |
| OpenFGA | Reachable without credentials. Veyntora creates its store (`veyntora`) and model. |
| Keycloak | The realm with the `veyntora` and `veyntora-sync` clients (`deploy/compose/keycloak/veyntora-realm.json` or `scripts/keycloak-realm.py`), and a `/platform-admins` group. The **issuer** is the realm URL as browsers reach it. The **address for the containers** is only needed when they reach Keycloak differently. |

After **Set up Veyntora**, migrate creates the tables, the permission model and the buckets, then syncs users and groups. That takes about a minute. Then sign in with a member of `/platform-admins`.

## When starting fails

The Setup page shows migrate's last error, for example a Keycloak client that is missing a role. Logs: `docker compose logs migrate`.

- **Not set up before:** **Change settings**, fix, save again. Passwords have to be entered again.
- **After a change in Admin → Infrastructure:** the Setup page offers **Go back to version N**, with the setup code (`make setup-code`).

## Changing a service

**Admin → Infrastructure → Change** on the service:
- Passwords left empty keep the ones in use.
- **Save and restart** tests the change first. Then every Veyntora service restarts with it; changing Keycloak signs everyone out.
- Every change is a new version under **Versions**, and **Go back to this** restores one.
- Changes are in the audit log (`infrastructure.update`, `infrastructure.restore`), with no passwords.

### Moving PostgreSQL

Saving a new address doesn't move the data. Move it first:

```bash
pg_dump -Fc --no-owner -d veyntora > veyntora.dump      # and the same for aegra
pg_restore --no-owner --role=veyntora -d veyntora veyntora.dump
```

Then create `veyntora_runtime` on the new server, change PostgreSQL in Admin → Infrastructure, and save.

### Moving S3

Copy both buckets with their object retention (for example `rclone sync --s3-object-lock`, or boto3 keeping `ObjectLockMode` and `ObjectLockRetainUntilDate`), then change S3.

### Moving OpenBao

Veyntora can't read its own provider and user keys (ADR 0004), so it can't move them:
1. Copy the KV secrets with a root token on both sides (the latest version of each is enough).
2. Change OpenBao's address, and enter an admin token for the new one so Veyntora's tokens are issued there.

A new address is refused while it doesn't hold Veyntora's passwords.

### New OpenBao tokens

Enter an admin token under OpenBao and save. The old tokens are not revoked; they lapse after 32 days without renewal.

## Where it is kept

- **`config` volume** (`/var/lib/veyntora`):
  - `infra.json` and `history/`: the versions;
  - `bootstrapped.json`: migrate's last result;
  - `set-up`: written once Veyntora has run.
- **OpenBao**, at `kv/veyntora/infra/*`: the passwords.
- **`.env`**: the four `VEY_CONFIG_*` keys. Without them, the file can't be opened. If you lose them, run `make env` for new keys and set Veyntora up again; the data in your services stays.

## Settings from the environment

CI (`make env-ci`, `deploy/compose/ci-infra.yaml`) and Helm set the services through `VEY_*` variables. Without a config file, the launcher uses those as they are, and Admin → Infrastructure shows them read-only.
