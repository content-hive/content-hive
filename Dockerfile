FROM python:3.13-slim-trixie

ARG APP_VERSION=0.1.0

LABEL org.opencontainers.image.title="Content Hive" \
      org.opencontainers.image.description="Content Hive - A content parsing service" \
      org.opencontainers.image.authors="The Content Hive Team" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PLAYWRIGHT_BROWSERS_PATH=/config/ms-playwright

WORKDIR /app

# Install system dependencies required by Playwright (without browsers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libatspi2.0-0 \
    libxshmfence1 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create deps directory for runtime plugin dependencies
RUN mkdir -p /app/deps && chmod 777 /app/deps

# Copy application code
COPY contenthive ./contenthive
COPY alembic ./alembic
COPY alembic.ini .

# Inject build-time version into const.py, then remove the script
COPY scripts/write_version.py write_version.py
RUN python write_version.py "${APP_VERSION}" && rm -rf write_version.py

COPY entrypoint /entrypoint
RUN chmod +x /entrypoint

EXPOSE 6123

VOLUME /config

ENTRYPOINT [ "/entrypoint" ]