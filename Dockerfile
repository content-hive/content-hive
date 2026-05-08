FROM python:3.13-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ARG APP_VERSION=0.1.0

LABEL org.opencontainers.image.title="Content Hive" \
      org.opencontainers.image.description="Content Hive - A content parsing service" \
      org.opencontainers.image.authors="The Content Hive Team" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    UV_NO_CACHE=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Create deps directory for runtime plugin dependencies
RUN mkdir -p /app/deps && chmod 777 /app/deps

# Copy application code
COPY contenthive ./contenthive
COPY alembic ./alembic
COPY alembic.ini .

COPY entrypoint /entrypoint
RUN chmod +x /entrypoint

EXPOSE 6123

VOLUME /config

ENTRYPOINT [ "/entrypoint" ]