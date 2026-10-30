# 0012 · Fast RAG graph, chat proxy and grounding (Phase 1)

Status: accepted · 2026-10-30 · Phase 1

## The graph reads Veyntora's database

The `fast_rag` graph runs in the graph server (Aegra) and imports `veyntora-api` for the database models, the OpenFGA client and the adapter runtime. Everything that decides what a user may see is derived there from the verified token:

- the user comes from `langgraph_auth_user` only. Aegra keeps a client-sent `configurable.user_id`, so that value is never used;
- the user's principals come from PostgreSQL memberships;
- chat access comes from OpenFGA (`can_chat`);
- the pipeline is the chatbot's live version, or the canary version for a stable hash bucket of users.

The alternative, having the API compute a "run context" and pass it as run input, would let anyone holding a token call the graph server directly with forged principals. The graph server connects with the same database role as the API. A narrower role is a Phase 7 hardening item.

## Retrieval is permission-aware twice

1. Qdrant filters by the caller's principals inside the search (ADR 0010), restricted to the chatbot's attached sources and its index profile.
2. Every hit is re-checked against the document's current ACL and status in PostgreSQL. Revoking access or deleting a document takes effect on commit, before the ACL sync or the deletion job has touched the index.

If no source passes the reranker's minimum score, the model is not called and the user gets the "I couldn't find this" answer with a hand-off offer.

## Grounded or silent

- The model sees numbered sources and must cite them as `[n]`, or reply `NO_ANSWER`.
- In the default mode (`if_ungrounded: no_answer`, `groundedness_action: block`) **nothing is streamed before the check passes**. The user sees progress events (searching, writing), then the checked answer. An answer is blocked when it cites nothing (citations required), cites a source number it was not given, or its groundedness is below the threshold (default 0.7).
- Groundedness in Phase 1 is lexical: the share of sentences with at least half of their content words (compared by 5-letter prefix, for German and English inflection) in a source they cite. A model-based judge can be added as an output guardrail instance with the Guardrails page (Phase 2).
- In "warn" mode tokens stream live and the answer carries a warning.

## External models

The run refuses an external provider (embedding, reranker or LLM) unless the chatbot's data rule lists it, even if this was checked at publish time. Data rules default to "mask personal data before external providers". PII masking (Presidio) arrives with guardrails in Phase 2, so until then such a chatbot cannot publish or run with an external model. Switching masking off is an explicit, audited data-rule change. Every stored answer records `external_egress`.

## Chat proxy

The browser never reaches the graph server. `/v1/chat/lg/...` forwards the LangGraph client's calls with the user's access token:

- only thread create/search/get/state/history and run stream/join/cancel are forwarded;
- only the `fast_rag` graph runs;
- the run body is rebuilt from one human message and the chatbot id: no client config, checkpoint, webhook or injected history;
- chatbot access is checked before the run starts.

Threads are owned by the token's subject (the Aegra auth hook). A thread stays with one user and one chatbot.

## Stored per answer

The conversation, the question, and the answer are stored, with: mode, pipeline version, tokens, latency, groundedness, external egress, the run id as trace id, and the cited chunks (document, ordinal `n`, quote, score, page). Feedback and hand-off requests attach to the answer.

## Chat UI

The chat uses the LangGraph client's `useStream` (`@langchain/langgraph-sdk` 1.12.4) against the proxy, with components built on Veyntora's design system to match the prototype. assistant-ui is **not** used for now:

- its runtime renders tokens as they stream, while the default "block" mode shows nothing before the grounding check;
- the citation chips, no-answer and hand-off states, and data-egress badge are custom anyway;
- adding it later only changes the presentation layer.

**Open question for the product owner:** should assistant-ui be adopted for the agent screens in Phase 3?

- Answer text is parsed into paragraphs, bold runs and `[n]` citation chips and rendered as React text. Model output is never inserted as HTML.
- A new chat starts on Home: a thread is created, then `/chat/<thread>` sends the first question once. The conversation row is written with the first answer.
- Auto and Agent modes, attaching files, sharing and "report wrong source" are shown disabled with the phase that builds them.
