# 0032 · Model, data and observability services are not bundled

Status: accepted · 2026-11-03 · Changes the local stack of ADR 0010 and ADR 0024

## Context

The compose stack started its own copies of many services:

- **Models and data:** Qdrant, a LiteLLM proxy, TEI (embedder and reranker), vLLM and Docling.
- **Observability:** Langfuse with ClickHouse, and an OTel collector feeding Prometheus, Loki and Grafana.

Veyntora never depended on these copies. It reaches the vector store, parser and models through provider instances (Providers & keys), and Langfuse and Grafana through Integrations. Each has its own address and a key in OpenBao. The bundled copies took memory and downloads (several GB of models), and they implied a fixed setup that real installations do not have.

## Decision

- **Removed from compose:**
  - **Models and data:** `qdrant`, `litellm`, `tei-embed`, `tei-rerank`, `vllm`, `docling`.
  - **Observability:** `clickhouse`, `langfuse-worker`, `langfuse`, `otel-collector`, `prometheus`, `loki`, `grafana`.
  - **Also gone:** their configuration, volumes, databases, storage bucket and `.env` secrets, plus the `bundled-langfuse`, `bundled-grafana`, `local-models` and `gpu` profiles.
- **Still bundled:** what the platform runs on, which is PostgreSQL, Valkey, S3 (SeaweedFS), OpenBao, OpenFGA and Keycloak (optional, `bundled-keycloak`). Also ClamAV, the code-interpreter sandbox, Mailpit and the Veyntora services.
- **Services you provide:** you run or rent the vector store, parser, models (LLM, embedder, reranker; any OpenAI-compatible API, including LiteLLM, vLLM or TEI), Langfuse and monitoring. You add them in the admin console, as Helm deployments already did.
- **Status page:** it no longer probes fixed addresses. `vector_store`, `models`, `embedding`, `parser` and `reranker` use the last checked health of the enabled providers with that capability.
  - A check fails when every such provider was found down.
  - The first four also fail when no such provider exists. A reranker is optional.
- **Integrations seed:** `bootstrap` imports Langfuse and Grafana only from `VEY_LANGFUSE_URL`, `VEY_GRAFANA_URL` and their keys, which are empty by default.
- **Metrics and spans:**
  - The API, graph server and OpenFGA still expose Prometheus metrics. `deploy/observability/` has example scrape jobs and the Grafana dashboard for your own monitoring.
  - The services no longer send their own spans or logs over OTLP. Answer traces go to the Langfuse set up in Integrations.

## Consequences

- **First run:** a new installation needs parser, embedding, vector-store and model providers before chatbots can be published. The publish checks and the setup guide already ask for them.
- **Existing stacks:**
  - Integrations entries pointing at `http://langfuse:3000` or `http://grafana:3000` fail their checks until they are changed or removed.
  - Old Docker volumes stay until they are deleted by hand: `qdrant`, `clickhouse`, `hf-*`, `prometheus`, `loki` and `grafana`.
- **Logs:** they are read with `docker compose logs`, or collected by your own log shipper.
