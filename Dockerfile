FROM python:3.12-slim

ARG APP_VERSION=0.1.0

LABEL version="${APP_VERSION}" \
      description="Content Hive - A content parsing service" \
      maintainer="shaoxiaof@hotmail.com"

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PLAYWRIGHT_BROWSERS_PATH=/config/ms-playwright \
    APP_VERSION=${APP_VERSION}

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
    libheif1 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY contenthive ./contenthive
COPY alembic ./alembic
COPY alembic.ini .

COPY entrypoint /entrypoint
RUN chmod +x /entrypoint

EXPOSE 6123

VOLUME /config

ENTRYPOINT [ "/entrypoint" ]