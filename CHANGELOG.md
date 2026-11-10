# Changelog

Notable changes, newest first. Versions follow [Semantic Versioning](https://semver.org).

## Unreleased

## 1.0.0 · 2026-11-10

The first release: a self-hosted knowledge platform with answers from documents people may read, agents that ask before they act, and a web console for every setting. What changed most in the weeks before it:

### Added

- **Reading per data source** (ADR 0040): Auto, fast text (pypdf), layout (Docling) or a vision model per page; file types, size and include/exclude patterns; re-read everything.
- **Apache Tika** as a second document parser.
- **pgvector** as a second vector store (ADR 0042): chunks in PostgreSQL, hybrid search with full-text search, permissions in every query.
- **Websites** (ADR 0041): sign-in (token, basic, cookie, header), JavaScript rendering through an optional browser service, sitemaps (also compressed), ignore `?query`, subdomains, a delay between requests.
- **Small talk** (ADR 0039): a labelled reply to greetings and "what can you do?", in Fast and Agent mode.
- **Chatbot details** editable after creating: name, short name, description, welcome message; copy settings or sources from another chatbot.
- **Knowledge health**: each finding lists its documents with Re-read, Exclude and Use again.
- **Notifications**: tabs, day groups, an icon per kind.
- **Data subject requests** can be rejected with a reason.
- **`make e2e-stack`**: every end-to-end test on its own throwaway stack.
- **Walkthroughs**: 20 recordings and a five-minute tour.

### Changed

- Pipeline settings grouped under sub-headings; the wizard opens on step 1 (Ingestion).
- Admin console sidebar grouped as Build, Knowledge, Connections, Operate, Govern.
- German texts address people as "Sie".

### Fixed

- Environment mode: migrate and the services agree on the version, so a stack set up from the environment no longer waits on the Setup page.
- Two uploads at once no longer fail when creating "My files".
- A step just added to an automation stays open in its editor.
- Dates read the same in the server's and the browser's engine (no React error in Safari).
- Images take Debian security updates at build time.
- Titles that are author lines or headings are replaced by one from the file name.
