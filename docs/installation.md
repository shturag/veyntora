# Installing Veyntora

This guide takes you from an empty machine to a working Veyntora with its first chatbot. Pick one of three ways:

| Way | For | Time |
|---|---|---|
| [A. Try it on your computer](#a-try-it-on-your-computer) | A first look. Veyntora starts throwaway copies of every service it needs. | About 15 minutes |
| [B. Install on a server with Docker Compose](#b-install-on-a-server-with-docker-compose) | A team or company, using your own PostgreSQL, Keycloak and the other services | About an hour, once the services exist |
| [C. Kubernetes](#c-kubernetes) | Platform teams running Argo CD | See [runbooks/deploy.md](runbooks/deploy.md) |

After installing, continue with [First steps in the admin console](#first-steps-in-the-admin-console).

## What you need

**For A and B:**
- Docker Engine or Docker Desktop, with Compose v2.20 or later.
- `git`, `make` and `openssl`.
- Memory:
  - Veyntora's own services need about 4 GB.
  - Way A also runs the services it depends on, including a virus scanner. Give Docker 8 GB or more; with too little, the scanner keeps restarting.
- Network access to the AI models you plan to use (your own, such as vLLM or Ollama, or external APIs).

**Only for way B,** your own installations of:

| Service | Used for |
|---|---|
| PostgreSQL 16 | Configuration, chats, audit log |
| Valkey or Redis | Queues and caches |
| An S3-compatible store | Uploaded documents and the write-once audit archive |
| OpenBao | Every secret: API keys, passwords, tokens |
| OpenFGA | Who may do what |
| Keycloak | Sign-in, users and groups |

What each one needs exactly (roles, buckets, clients) is in [runbooks/infrastructure.md](runbooks/infrastructure.md).

## Get the code

```bash
git clone <your Veyntora repository URL> veyntora
cd veyntora
```

All commands below run in this folder. `make help` lists every command.

## A. Try it on your computer

```bash
make env-ci   # writes .env with random passwords for throwaway services
make up       # builds and starts Veyntora and those services
```

The first start builds the images and takes several minutes. When `make ps` shows the services as `healthy`:

1. Open **http://localhost:3000**.
2. Sign in as **admin**. The password was generated for you:

   ```bash
   grep VEY_DEV_ADMIN_PASSWORD .env
   ```

   There is also an **employee** account without admin rights (`VEY_DEV_EMPLOYEE_PASSWORD`), so you can see what employees see.
3. Continue with [First steps in the admin console](#first-steps-in-the-admin-console).

These throwaway services are for trying Veyntora and for tests only. Their data is deleted with `make reset`. Don't put real company data in them.

## B. Install on a server with Docker Compose

### 1. Prepare your services

Set up the six services from [What you need](#what-you-need) as described in [runbooks/infrastructure.md](runbooks/infrastructure.md). In Keycloak:
- import the realm from `deploy/compose/keycloak/veyntora-realm.json`, or create it with `scripts/keycloak-realm.py`;
- add the people who will run Veyntora to the group **`/platform-admins`**.

### 2. Choose the address

Decide the address people will use, for example `https://veyntora.example.com`. Then:
- In Keycloak, client **`veyntora`**: set the redirect URI to `https://veyntora.example.com/api/auth/callback` and the web origin to `https://veyntora.example.com`.
- Put the same address in `.env` after the next step:

  ```bash
  VEY_PUBLIC_BASE_URL=https://veyntora.example.com
  ```

### 3. Create the configuration keys

```bash
make env
```

This writes `.env` with the keys that encrypt the settings you enter in the browser.
- **Keep a copy of `.env` somewhere safe**, for example in your password manager. Without these keys, Veyntora can't read its settings and has to be set up again; your data in the services stays.
- Never commit `.env`; it is already in `.gitignore`.

### 4. Start Veyntora

```bash
make up
make setup-code   # the one-time code the Setup page asks for
```

### 5. Put a reverse proxy in front

Veyntora's ports listen on `127.0.0.1` only. Publish the web app (port 3000) through your reverse proxy with HTTPS. Turn off response buffering, so answers appear as they are written. An example for nginx:

```nginx
server {
  listen 443 ssl;
  server_name veyntora.example.com;
  # ssl_certificate …; ssl_certificate_key …;

  location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
    proxy_read_timeout 300s;
  }
}
```

Keycloak must also be reachable from people's browsers at the address you enter as its **issuer**.

### 6. Set Veyntora up in the browser

1. Open your address. It shows the **Setup page**.
2. Enter the setup code from step 4.
3. Fill in each of the six services and click **Test connection** on each.
4. Click **Set up Veyntora**. It creates the tables, the permission model and the buckets, then reads users and groups from Keycloak. That takes about a minute.
5. Sign in with an account in `/platform-admins`.

If a step fails, the Setup page shows the error; [runbooks/infrastructure.md](runbooks/infrastructure.md#when-starting-fails) explains what to do. Later changes to these services are made under **Admin → Infrastructure**.

## C. Kubernetes

The Helm chart, the values per environment and the Argo CD setup are described in [runbooks/deploy.md](runbooks/deploy.md): database roles, secrets through External Secrets, OpenBao Kubernetes auth, buckets, ingress and backups.

## First steps in the admin console

Open the admin console from the account menu (bottom left). Short recordings of each step are in [walkthroughs](walkthroughs/README.md).

1. **Add a virus scanner** under **Integrations → Virus scanner**. Way A has one already. Until one is set up, uploaded files wait and are not indexed.
2. **Add your AI providers** under **Providers & keys → Add provider**, and click **Test connection** on each:

   | Provider | Needed for |
   |---|---|
   | Language model (LLM) | Every chatbot: it writes the answers |
   | Embedding model | Chatbots that answer from documents |
   | Vector store: Qdrant or pgvector | Chatbots that answer from documents. **pgvector** keeps the chunks in a PostgreSQL you already run (address `postgresql://user@host:5432/db`, the password as the key) |
   | Document parser: Docling or Apache Tika | Reading PDFs, Word files and pages. **Docling** reads layout, tables and scans; **Apache Tika** reads almost any file type, fast (`docker run -p 9998:9998 apache/tika:4.2.0-full`, endpoint `http://host.docker.internal:9998`; the `-full` image adds OCR). Each data source chooses its reader under **How documents are read** |
   | Reranker | Optional: better ordering of search results |
   | Vision model (VLM) | Optional: describes pictures and charts, and can read scans and forms. Choose it on the data source (**How documents are read**) or in the chatbot's **Pipeline → Ingestion**. Docling calls it itself, so start Docling with `DOCLING_SERVE_ENABLE_REMOTE_SERVICES=true` |

   Websites built by scripts need the optional browser service: `docker compose --profile browser up -d`, and `VEY_BROWSER_URL=ws://browser:3000/` in `.env` (then `make up`). Turn on **Render JavaScript** on the website source.

   Keys go straight to OpenBao and are never shown again; the page shows only their last 4 characters.
3. **Connect a data source** under **Data sources → Connect data source**: SharePoint, Confluence, a file share, Nextcloud, S3, Git, a website, ServiceNow, Jira, a database, or files you upload. Sources with their own permissions keep them. Wait until the documents show **Indexed**.
4. **Create a chatbot** under **Chatbots → New chatbot**. The five steps:
   - **Basics:** name, description and welcome message.
   - **Knowledge:** the sources it answers from.
   - **Pipeline:** what it should do and which models it uses.
   - **Access:** who may use it, and its data rule.
   - **Test & publish:** try it in the Playground, then publish.
5. **Check as an employee.** Sign in as someone in the groups you gave access to and ask a question on **Home**. Answers show numbered sources.

Optional, when you need them:
- Langfuse traces and Grafana dashboards: **Integrations** ([runbooks/external-services.md](runbooks/external-services.md)).
- Microsoft Teams, Slack, the web widget and the REST API: **Channels & API**.
- Email: **Channels & API → Email**.

## Updating

1. Back up first (see the next section).
2. Get the new version and restart:

   ```bash
   git pull
   make up
   ```

The **migrate** service updates the database. Follow it with `docker compose logs -f migrate`. If it fails, those logs and the Setup page show the error; fix it and run `make up` again.

## Backups

| What | How |
|---|---|
| `.env` | Keep a copy safe (see step 3 of way B). It holds the keys to Veyntora's settings. |
| PostgreSQL | Databases `veyntora` and `aegra`: `pg_dump -Fc --no-owner`, or your provider's point-in-time recovery |
| S3 | Both buckets, including the audit bucket's object retention |
| OpenBao | Raft snapshots: `bao operator raft snapshot save` |
| The `config` volume | The settings from the Setup page and their history |
| Vector store | Optional: it can be rebuilt by re-indexing the sources |

Restoring and moving services is described in [runbooks/infrastructure.md](runbooks/infrastructure.md) and [runbooks/deploy.md](runbooks/deploy.md#6-backups-and-restore).

## Stopping and removing

```bash
make down    # stop; all data is kept
make reset   # stop and delete Veyntora's local volumes (asks first)
```

With way B, your own services and their data are not touched by either command.

## Common problems

| Problem | What to do |
|---|---|
| `make up` says there is no `.env` | Run `make env` (way B) or `make env-ci` (way A) first. |
| The page keeps showing the Setup page | Setup isn't finished, or migrate failed: see the error on the page and `docker compose logs migrate`. |
| Sign-in fails or loops | `VEY_PUBLIC_BASE_URL` and the Keycloak client's redirect URI must match your address exactly, including `https`. |
| Uploaded documents stay "Waiting" | Add a virus scanner, a document parser and an embedding model, and check them with **Test connection**. |
| The virus scanner restarts with exit 137 | Give Docker more memory. |
| Answers appear all at once, not word by word | Turn off response buffering in your reverse proxy. |
| A chatbot answers "I couldn't find this" to "Hi" or "What can you do?" | Turn on **Reply to small talk** in its Pipeline → Generation, and give it a description. |
| Scanned PDFs come out empty | The source reads them with **Fast text**; choose **Auto** or **Layout** under *How documents are read*. |
| A website's pages come out nearly empty | The site is built by JavaScript: start the browser service and turn on **Render JavaScript** on the source. |
| A website needs a sign-in | Choose the sign-in on the source (token, user name and password, cookie or header); start pages must be `https://`. |
| Files a source should skip are still there | Check **Which files** on the source; skipped files are removed at its next complete sync (**Sync now**). |
| A document has an author name or "Abstract" as its title | Read it again (Knowledge health or the source page); titles that are not titles are replaced by one from the file name. |

More in [runbooks/local-dev.md](runbooks/local-dev.md#troubleshooting). Service status: `make ps`; logs: `make logs`.
