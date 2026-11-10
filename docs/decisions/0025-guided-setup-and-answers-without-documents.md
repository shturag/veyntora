# 0025 · Guided setup; answers without documents as a labelled exception

Status: accepted · 2026-11-02

## Product owner decisions

- **No ready-made chatbots.** Instead, the new-chatbot wizard and the Pipeline page ask what the chatbot should do. The answers set its modes and steps, and only the providers that setup needs are asked for.
- **A general chat without documents is allowed**, as an exception to "grounded or silent". Each chatbot's data rule must allow it. Every such answer is labelled "No sources", and the Governance page lists these chatbots.
- **Docling and Qdrant are not registered automatically.** Admins add them under Providers & keys.

## Guided setup

It asks four questions:
1. **Where do answers come from:** documents, or none?
2. **Tasks:** should it carry out tasks with tools (adds the agent)? With documents, should it rerank, and hand questions to expert teams?
3. **Providers:** only the ones those answers need, each with an "add one" link when none exists.
4. **System prompt:** a suggestion that follows the answers until the admin writes their own.

Applying the answers:
- writes the draft (`retrieval.enabled`, `rerank.enabled`, `router.allowed_modes` and the provider references);
- sets the standard flow's picture;
- sets the expert teams.

Nothing is published.

## Checks follow usage

`PipelineSpec.publish_problems` requires only what the chatbot uses:
- **Always:** the answer model and a system prompt.
- **With documents:** parser, embedding (the same for ingestion and retrieval) and vector store.
- **With reranking:** a reranker.
- **With the agent reachable:** an agent model.

A chatbot without documents also needs:
- the data rule's `allow_no_documents`, checked when publishing and on every run;
- the standard pipeline, because a custom flow's grounding checks assume documents.

## Answers without documents

- **What happens at run time:**
  - Input checks and masking run as usual.
  - Nothing is searched.
  - The model gets rules that forbid stating company-specific facts as known.
  - The output check still runs.
- **How the answer is marked:** it carries `no_sources`, and the chat shows "Answered without documents" with a "No sources" badge.
