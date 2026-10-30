# syntax=docker/dockerfile:1.7
# LangGraph server (Aegra) with the fast_rag, agent and router graphs.
# Build from the repository root: docker build -f services/graphs/Dockerfile .

FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

FROM python:3.12.16-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src

COPY pyproject.toml uv.lock ./
COPY packages/spec/pyproject.toml packages/spec/
COPY packages/providers/pyproject.toml packages/providers/
COPY services/api/pyproject.toml services/api/
COPY services/graphs/pyproject.toml services/graphs/
COPY services/workers/pyproject.toml services/workers/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package veyntora-graphs

COPY packages/spec packages/spec
COPY packages/providers packages/providers
COPY services/graphs services/graphs
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package veyntora-graphs

FROM python:3.12.16-slim-trixie
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
# Aegra loads graphs by file path relative to aegra.json.
COPY services/graphs/aegra.json /app/services/graphs/aegra.json
COPY services/graphs/src /app/services/graphs/src
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AEGRA_CONFIG=/app/services/graphs/aegra.json
WORKDIR /app/services/graphs
USER 10001:10001
EXPOSE 2026
CMD ["aegra", "serve", "--host", "0.0.0.0", "--port", "2026"]
