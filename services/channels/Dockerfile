# syntax=docker/dockerfile:1.7
# Image for the channels service (Teams and Slack bots).
# Build from the repository root: docker build -f services/channels/Dockerfile .

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
COPY services/channels/pyproject.toml services/channels/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package veyntora-channels

COPY packages/spec packages/spec
COPY packages/providers packages/providers
COPY services/api services/api
COPY services/channels services/channels
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package veyntora-channels

FROM python:3.12.16-slim-trixie
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /var/lib/veyntora && chown app:app /var/lib/veyntora
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER 10001:10001
EXPOSE 8010
CMD ["uvicorn", "veyntora_channels.app:app", "--host", "0.0.0.0", "--port", "8010", "--proxy-headers"]
