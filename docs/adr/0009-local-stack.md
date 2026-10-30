# 0009 · Local stack choices

Status: accepted · 2026-10-30 · Phase 0

- **Valkey 9 instead of Redis.** Redis 7.4+ is no longer BSD-licensed. Valkey is a drop-in, Linux Foundation project, and Celery, Aegra and Langfuse use it unchanged.
- **Aegra 0.11** serves the LangGraph graphs (Agent Protocol v2, `useStream`, human-in-the-loop, custom auth, Postgres checkpointer, Redis worker queue). Its auth handler accepts only Keycloak tokens for the `veyntora-api` audience. In Phase 0 the three graphs are registered but refuse every run with `PhaseNotAvailableError`, so no placeholder can pass for an answer.
- **TEI on CPU** for BGE-M3 and bge-reranker-v2-m3. `deploy/compose/tei/Dockerfile` only selects the upstream image matching the machine's architecture, so `docker compose up` works on x86 and Apple Silicon. GPU nodes use the CUDA images (Helm).
- **vLLM** needs an NVIDIA GPU. It is behind the `gpu` profile (`VLLM_MODEL=… docker compose --profile gpu up`). The model choice belongs to Phase 1.
- **Langfuse v3** needs ClickHouse, Valkey and S3. It is included and initialised headlessly (org, project, keys, admin user from `.env`).
- **Memory.** The full stack needs about 12 GB, plus 4–6 GB for TEI loading BGE-M3. Give Docker Desktop at least 16 GB. With 8 GB, TEI and Langfuse get OOM-killed (exit 137).
- **Defaults.** Compose has development defaults for every secret so a plain `docker compose up` works. `make env` writes random values to `.env`. Helm has no defaults for secrets.
- **Ports** bind to 127.0.0.1 only.
- **Fonts** (Inter, JetBrains Mono) are self-hosted from npm (Fontsource). No runtime or build-time calls to Google.
