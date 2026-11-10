# 0037 · Vision models (VLMs) for reading documents

Status: accepted · 2026-11-08

## Context

Docling is the document parser: layout analysis, tables and OCR. It extracts born-digital text exactly, but it loses what is only in images:
- scans of poor quality, forms and handwriting;
- charts, diagrams and screenshots.

Its "Describe images" option ran a vision model configured inside the Docling server, which the admin console could not choose or see.

A vision-language model (VLM) reads these better. But it can misread or invent text, it is slow without a GPU, and an external one receives the documents. So it must not replace the parser.

## Decision

**1. A provider type "Vision model".**
- **What it is:** capability `vision`, adapter `openai_compatible`: any server with OpenAI-compatible chat completions that accepts images (vLLM, Ollama, LM Studio, hosted APIs).
- **Added like every provider:** Providers & keys → Add provider, with its key in OpenBao.
- **Connection test:** it sends one small image, so a text-only model fails it.

**2. Docling calls the model; Veyntora only chooses it.**
- **Ingestion settings:**
  - `vision_instance_id`: the vision model;
  - `vision_pages`: read whole pages with it.
- **What Docling does with it:**
  - with **Describe images**, it describes pictures (`picture_description_api`);
  - with **Read pages with the vision model**, its VLM pipeline turns every PDF and image page into Markdown (`pipeline=vlm`, `vlm_pipeline_model_api`).
- **Why these options:** they are the documented API forms in docling-serve 1.38, though marked deprecated there in favour of a free-form `custom_config`. Docling calls other services only with `DOCLING_SERVE_ENABLE_REMOTE_SERVICES=true`; otherwise it refuses, and the document fails with Docling's reason.

**3. The index profile includes the model while it is used.**
- **When it counts:** only with Describe images or Read pages. A chosen but unused model leaves the chunks as they are.
- **Existing profiles:** their keys stay the same.
- **A change:** choosing or changing the model re-indexes, like any other ingestion change.

**4. The same safety rules as other providers.**
- **External models:**
  - indexing uses a profile with an external vision model only when the chatbot's data rule allows it, as for an external parser or embedding model;
  - the publish check flags it too.
- **Reading pages:** "Read pages" without a vision model blocks publishing. Describe images without one falls back to Docling's own model.

## Consequences

- **What it adds:** scans, forms, charts and screenshots become searchable without a separate OCR product, and the admin sees and chooses the model like any other.
- **The key:** it is read from OpenBao by the worker and sent to Docling with each request, because Docling makes the call. Docling must be trusted with it like the worker. For a self-hosted model without a key, nothing is sent.
- **Reading pages is opt-in per pipeline.** It is slower and can misread text, which matters for "grounded or silent": the citation shows the model's transcription. Documents with a text layer should keep the standard pipeline.
- **Docling's API:** the options may be removed in a later docling-serve. Moving to `custom_config` then changes only the parser adapter.
