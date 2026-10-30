# 0015 · Pipeline editor and guardrails (Phase 2, part 1)

Status: accepted · 2026-10-30 · Phase 2

## Pipeline editor

- **Pages:** the 7 Pipeline pages (ingestion, retrieval, reranking, generation, agent, router, guardrails) edit the chatbot's draft spec, one section per page.
- **One form for all:** a single form is driven by field descriptors (`apps/web/src/lib/pipeline.ts`), with the generated `PipelineSpec` types.
- **Saving:** a save replaces the draft (`If-Match`: chatbot version) and is audited.
- **Publishing:** the side panel lists what still blocks publishing, and Publish uses the API's checks.
- **Agent and Router:** these settings are saved now; their runtime arrives in Phase 3, and the pages say so.
- **Errors:** the API's validation reasons are shown to the user as written.

## Retrieval settings that were stored but not applied

- **Metadata filter:** a strict language, `key = value` and `key in [a, b]` joined by AND (`veyntora_spec.filters`). Keys are limited to indexed payload fields (`language`, `source_id`, `document_id`). The filter can only narrow a search: `source_id` is intersected with the chatbot's own sources, and permission filters are always added. Invalid filters are refused when the draft is saved.
- **Minimum matching terms:** candidates must contain at least N distinct words of the question (compared by 5-letter prefix, as in grounding).
- **Semantic chunking:** sections are split where neighbouring sentences stop being similar (cosine over the pipeline's own embeddings) or before the size limit. The threshold is part of the index profile only for semantic chunking, so other profiles keep their keys.
- **German compound splitting: still not applied.** It needs a German word list or a decompounding library (a new dependency). This is an open question for the product owner. The toggle is saved, but has no effect yet.

## Guardrails (product owner: external PII API, Llama Guard via API)

- **Personal data:**
  - local rules always run: e-mail, IBAN, Luhn-checked card numbers, phone;
  - when the pipeline names a PII provider, its entities are added. `azure_pii` uses Azure AI Language PII recognition, which handles German and English.
  - **Mask:** before an external model sees the question, sources or history, values are replaced with stable placeholders (`[EMAIL_1]`) and put back in the answer. Masked answers are never streamed.
  - **Block:** a question containing personal data is refused.
  - **Data rule:** when it says "mask before external providers", external models are allowed once the pipeline has a PII provider. The PII provider is itself external, so it must be allowed by the data rule, but it is exempt from masking.
  - **Documents** are not masked before embedding, so an external parser or embedder still needs the masking rule off (fail closed).
- **Safety checks:** `llama_guard` uses any OpenAI-compatible provider that serves Llama Guard, via `/completions` with the raw Llama Guard 3 prompt. The 13 standard categories are kept, and custom ones are added:
  - prompt injection (input);
  - each blocked topic (input; refuse, or hand off to a person);
  - promises (output).

  Local injection patterns run even without a safety check. Blocked topics and "no promises" need their check instance; publishing refuses otherwise.
- **The "no promises" default is now off.** It was never enforced before, and now it needs an output check.
- **Data rules apply to guard providers too:** every guard provider is subject to the chatbot's data rule, and its use marks the answer as external.
- **Not yet tested against the live Azure and Llama Guard services.** Tests use mocked responses in the documented shapes.
