# 0038 · Open source under the Apache License 2.0

Status: accepted · 2026-11-08 · supersedes the licence in ADR 0002

## Context

Veyntora was proprietary (ADR 0002). It is meant to run on infrastructure its users host and control (ADR 0033), often in organisations that must be able to inspect, audit and adapt the software that handles their documents. Publishing the source serves that, and lets others contribute connectors, providers and translations.

## Decision

- **License:** Apache-2.0, for the whole repository. It is permissive and includes a patent grant, which matters to companies adopting infrastructure software. `LICENSE` holds the text; `NOTICE` names the copyright holder ("The Veyntora Authors") and the third-party licenses that are not permissive.
- **Contributions:** licensed under Apache-2.0 as they come in (inbound = outbound), without a separate contributor licence agreement. `CONTRIBUTING.md` says so.
- **Dependencies:** must be compatible with Apache-2.0. Weak copyleft (LGPL, MPL) is accepted for libraries used unmodified; GPL and AGPL libraries are not added to the code that ships.
- **Before publishing:** the UI prototype the screens were built from was not ours to publish. It was removed from the repository and from its whole history, together with the references to its files. Commit author addresses were replaced by the GitHub no-reply address.
- **Security reports** go through GitHub's private vulnerability reporting (`SECURITY.md`).

## Consequences

- Anyone may use, change and redistribute Veyntora, including in closed products, as long as they keep the notices.
- The history was rewritten once, so clones made before then must be cloned again.
- Third-party services that Veyntora connects to (Keycloak, OpenBao, Docling and others) keep their own licenses; they are not part of this repository.
