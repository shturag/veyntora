# syntax=docker/dockerfile:1.7
# Image for the API, the migrate/bootstrap job, Celery workers and the scheduler.
# Build from the repository root: docker build -f services/api/Dockerfile .

FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.12.16-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src

# Dependencies first (cached unless the lock file changes).
COPY pyproject.toml uv.lock ./
COPY packages/spec/pyproject.toml packages/spec/
COPY packages/providers/pyproject.toml packages/providers/
COPY services/api/pyproject.toml services/api/
COPY services/graphs/pyproject.toml services/graphs/
COPY services/workers/pyproject.toml services/workers/
COPY services/channels/pyproject.toml services/channels/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package veyntora-workers

COPY packages/spec packages/spec
COPY packages/providers packages/providers
COPY services/api services/api
COPY services/workers services/workers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package veyntora-workers

FROM python:3.12.16-slim-trixie
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /var/lib/veyntora && chown app:app /var/lib/veyntora
COPY --from=build /opt/venv /opt/venv
COPY services/api/alembic.ini /app/services/api/alembic.ini
COPY services/api/alembic /app/services/api/alembic
COPY deploy/openfga/model.json deploy/openfga/bootstrap.json /app/deploy/openfga/
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VEY_ALEMBIC_INI=/app/services/api/alembic.ini \
    VEY_OPENFGA_MODEL_PATH=/app/deploy/openfga/model.json
WORKDIR /app
USER 10001:10001
EXPOSE 8000
CMD ["veyntora-api", "serve"]
