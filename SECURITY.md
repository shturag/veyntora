# Security policy

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Report them privately through GitHub: on the repository page, open **Security → Report a vulnerability**.

Include what you found, how to reproduce it, and what an attacker could do with it. We aim to answer within a week. We'll agree on a date to publish once a fix is out, and credit you if you like.

## Supported versions

Fixes go into the latest release on `main`. Run the newest version; updates migrate the database by themselves ([docs/installation.md](docs/installation.md#updating)).

## How Veyntora protects data

What the design relies on, so a report can say which promise breaks:

- **Secrets are write-only.** Keys and passwords are stored in OpenBao and never returned by the API, written to logs or sent in traces.
- **Permission-aware answers.** Retrieval only returns documents the asking person may read; permissions from the source system are mapped and fail closed.
- **Authorization on every request** with OpenFGA. The browser holds an HTTP-only session cookie; writes need a CSRF header.
- **No write without approval.** Agent tools that change data wait for a person.
- **Data rules per chatbot.** External providers, traces and answers without documents are off unless allowed; personal data can be masked before anything leaves the network.
- **A tamper-evident audit log** with a hash chain and write-once archive.

The architecture decisions are in [docs/adr](docs/adr/README.md); ADR 0004 covers secrets and ADR 0005 authorization.

## Running it safely

- Keep `.env` (the configuration keys) secret, and back it up.
- Publish only the web app, behind HTTPS (see [docs/installation.md](docs/installation.md)). The other ports listen on `127.0.0.1`.
- Keep the services Veyntora depends on (PostgreSQL, Keycloak, OpenBao and the others) patched and not reachable from the internet.
