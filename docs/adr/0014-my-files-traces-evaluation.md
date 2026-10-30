# 0014 · My files, answer traces, evaluation runner (Phase 1)

Status: accepted · 2026-10-30 · Phase 1

## My files

- **What it is:** each user can have one personal upload source (`data_sources.uploaded_by`). Its documents' ACL names only that user. Admins don't see these sources in the console.
- **How they're searched:** every chat of the owner searches them, next to the chatbot's attached sources. The ACL filter keeps them invisible to everyone else, colleagues in the same groups included.
- **Indexing:** they are indexed for the live chatbots' published versions (not drafts). The same data-rule check as other sources applies before a file reaches an external provider. Upload checks, virus scan and size limits are those of admin uploads.
- **API and screens:** `GET/POST/DELETE /v1/me/files`. Both the Library panel and the paper clip in the composer upload there.
- **Retention:** no automatic deletion yet. Retention jobs arrive with governance (Phase 6), and the Help page says nothing about it until then.

## Answer traces in Langfuse

- **Transport:** one trace per answer, sent as OpenTelemetry spans to Langfuse's OTLP endpoint (`/api/public/otel/v1/traces`, project keys from compose).
  - We use the OpenTelemetry SDK, which is already locked, instead of the Langfuse SDK, whose current major version is newer than we can verify.
  - A dedicated tracer provider leaves the graph server's own telemetry untouched.
- **Contents:**
  - the question, the answer, the outcome, groundedness and external egress;
  - steps (rewrite, retrieve, rerank, generate) with timings, model and token usage;
  - source titles and scores.
- **Not in traces:** chunk text and prompts, so traces do not become a second copy of the documents.
- **Linking:** the trace id is stored on the answer (`messages.trace_id`). Tracing is off when no keys are set.
- **Verified locally:** a test trace was ingested by Langfuse with its spans, generation, model and usage, then deleted.

## The answer pipeline is shared code

`veyntora_api.rag` (pipeline, grounding, record, tracing) moved out of the graph package. The `fast_rag` graph and the evaluation runner use the same code. It has no LangGraph dependency.

## Evaluation runner

`veyntora-eval` (worker image) runs `evals/phase1`:

- It creates its own groups, sources and a draft chatbot with the given provider instances. For external providers it adds a data rule for this throwaway chatbot only.
- It indexes the fictional corpus and asks the 20 questions as an employee outside HR.
- It scores each answer:
  - answerable questions: citation into the expected document plus the expected facts;
  - unanswerable ones: no answer;
  - HR-only chunks seen by a non-HR user: must be zero;
  - p95 latency against 2.5 s.
- Afterwards it removes everything it created; audit entries stay. The exit code is non-zero on any failure.
- It needs provider keys, so it has not been run yet.
