# Architecture decision records

| # | Decision |
|---|---|
| [0001](0001-monorepo-and-toolchain.md) | Monorepo and toolchain, pinned versions and deviations |
| [0002](0002-product-decisions.md) | Product name, no demo data, licence |
| [0003](0003-auth-bff.md) | Sign-in runs in the API (BFF), sessions, CSRF |
| [0004](0004-secrets-write-only.md) | Secrets are write-only |
| [0005](0005-authorization-model.md) | Authorization model (OpenFGA) |
| [0006](0006-object-storage.md) | Object storage: customer S3, SeaweedFS locally |
| [0007](0007-audit-hash-chain.md) | Append-only, hash-chained audit log |
| [0008](0008-config-write-path.md) | One write path for configuration |
| [0009](0009-local-stack.md) | Local stack choices |
| [0010](0010-phase1-retrieval-and-providers.md) | Retrieval and provider adapters (Phase 1) |
| [0011](0011-ingestion.md) | Ingestion, index profiles, virus scan, chatbot setup (Phase 1) |
| [0012](0012-fast-rag.md) | Fast RAG graph, chat proxy, grounding (Phase 1) |
| [0013](0013-hosted-providers-and-sharepoint.md) | Hosted model APIs locally, Providers page, SharePoint connector |
| [0014](0014-my-files-traces-evaluation.md) | My files, answer traces, evaluation runner (Phase 1) |
| [0015](0015-pipeline-editor-and-guardrails.md) | Pipeline editor, retrieval settings, guardrails (Phase 2) |
| [0016](0016-playground-and-provider-resilience.md) | Playground and provider resilience (Phase 2) |
| [0017](0017-own-models-and-settings.md) | Own models (BYOK) and settings (Phase 2) |
| [0018](0018-german-compound-splitting.md) | German compound splitting (Phase 3) |
| [0019](0019-agent-approvals-router.md) | Agent, approvals and the Auto router (Phase 3) |
| [0020](0020-people-chatbots-channels-flows.md) | Users & groups, chatbot management, channels, custom flows (Phase 4) |
| [0021](0021-automations-knowledge-answers.md) | Automations, knowledge health, saved answers, hand-offs, delegated tools (Phase 5) |
| [0022](0022-evaluation-rollout-usage-operate.md) | Evaluation, canary roll-out, usage and budgets, operating screens, S3 and website connectors (Phase 6) |
| [0023](0023-governance-audit-connectors-hardening.md) | Governance, data subject requests, audit archive, access reviews, Confluence/database/file-share connectors, hardening (Phase 7) |
| [0024](0024-external-observability-and-identity.md) | Langfuse and Grafana as configuration, your own Keycloak |
| [0025](0025-guided-setup-and-answers-without-documents.md) | Guided setup; answers without documents as a labelled exception |
| [0026](0026-presidio-self-hosted-pii.md) | Presidio as a personal-data detector you connect |
| [0027](0027-chat-model-choice-and-thinking.md) | Model choice and thinking in the chat |
| [0028](0028-chat-attachments.md) | Files attached to a chat question |
| [0029](0029-web-search.md) | Web search in the chat |
| [0030](0030-code-interpreter.md) | Code interpreter: a sandbox in the stack |
| [0031](0031-embedding-and-rerank-costs.md) | Embedding and reranker usage and prices |
| [0032](0032-external-model-data-and-observability-services.md) | Model, data and observability services are not bundled |
| [0033](0033-infrastructure-you-host.md) | Veyntora runs on infrastructure you host |
| [0034](0034-infrastructure-set-up-in-the-browser.md) | The infrastructure is set up in the browser |
| [0035](0035-knowledge-tools-and-grounded-agents.md) | Knowledge tools, and agents that look things up |
