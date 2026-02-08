FROM python:3.12-slim

ARG APP_VERSION=0.1.0
ARG UID=1000
ARG GID=1000

LABEL version="${APP_VERSION}" \
      description="Content Hive - A content parsing service" \
      maintainer="shaoxiaof@hotmail.com"

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    APP_VERSION=${APP_VERSION}

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install browsers and system dependencies (as root)
RUN playwright install --with-deps chromium && \
    chmod -R 755 /ms-playwright

# Copy application code
COPY contenthive ./contenthive

# Create non-root user and set permissions
RUN groupadd -g ${GID} contenthive && \
    useradd -m -u ${UID} -g contenthive contenthive && \
    mkdir -p /config/data /config/logs /config/plugins && \
    chown -R contenthive:contenthive /app /config

USER contenthive

EXPOSE 6123

VOLUME [ "/config" ]

CMD ["uvicorn", "contenthive.main:app", "--host", "0.0.0.0", "--port", "6123"]