# 0005 · Authorization model (OpenFGA)

Status: accepted · 2026-10-30 · Phase 0

Model: `deploy/openfga/model.fga` (tests: `model.tests.fga.yaml`, run in CI). Object ids are Veyntora UUIDs.

| Type | Relations |
|---|---|
| `group` | `member` (users and nested groups), `owner` |
| `platform:default` | `platform_admin`, `knowledge_admin`, `security_reviewer`, `auditor` |
| `admin_area:<area>` | `editor`, `viewer` (auditors view everything, platform admins edit everything) |
| `chatbot` | `owner` (chatbot admin), `editor`, `approver`, `user`; derived `can_chat`, `can_approve`, `can_edit_content`, `can_edit_draft`, `can_publish`, `can_manage_access`, `can_view_admin` |
| `tool` | `caller` (from the chatbots that bind it), `approver`, `manager` (security reviewers) |
| `source` | `reader`, `manager` (knowledge admins) |

- The chatbot relations follow the prototype's Roles & permissions matrix (User, Approver, Editor, Chatbot admin, Platform admin). A person's highest role across their groups applies, because relations are unions.
- Which platform roles may edit or view which admin areas is **data, not code** (`deploy/openfga/bootstrap.json`). It is applied idempotently by `veyntora-api bootstrap` and becomes editable in the Roles & permissions UI (Phase 4).
- The API checks OpenFGA on every protected endpoint (`require_admin_area`, and per-object checks from Phase 1). The web app hides what the user cannot open but never relies on that for security.
- Document-level permissions are **not** modelled in OpenFGA. Source ACLs go into each chunk's Qdrant payload and are filtered at query time (Phase 1). OpenFGA decides who may attach and manage sources.
