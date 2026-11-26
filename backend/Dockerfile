# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH

ARG APP_UID=1000
ARG APP_GID=1000
# UID/GID совпадают с пользователем хоста, чтобы писать в ./config
RUN (getent group "$APP_GID" >/dev/null || groupadd --gid "$APP_GID" app) \
    && useradd --non-unique --no-log-init --create-home --uid "$APP_UID" --gid "$APP_GID" app

WORKDIR /app
RUN chown "$APP_UID:$APP_GID" /app

FROM base AS builder
RUN pip install --no-cache-dir uv==0.13.10
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

FROM builder AS builder-dev
RUN uv sync --frozen --no-cache

FROM base AS dev
COPY --from=builder-dev /opt/venv /opt/venv
COPY --chown=${APP_UID}:${APP_GID} . .
USER app
CMD ["sh", "scripts/start-api.sh", "--reload", "--reload-dir", "/app/app"]

FROM base AS prod
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY alembic ./alembic
COPY scripts ./scripts
COPY alembic.ini ./
USER app
CMD ["sh", "scripts/start-api.sh", "--proxy-headers", "--forwarded-allow-ips", "*"]
