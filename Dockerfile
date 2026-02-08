FROM python:3.12-slim

ARG APP_VERSION=0.1.0

LABEL version="${APP_VERSION}" \
      description="Content Hive - A content parsing service" \
      maintainer="shaoxiaof@hotmail.com"

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    APP_VERSION=${APP_VERSION} \
    PUID=1000 \
    PGID=1000

WORKDIR /app

# Install gosu for step-down from root
RUN apt-get update && \
    apt-get install -y --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/* && \
    gosu nobody true

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install browsers and system dependencies
RUN playwright install --with-deps chromium && \
    chmod -R 755 /ms-playwright

# Copy application code
COPY contenthive ./contenthive

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create config directories
RUN mkdir -p /config/data /config/logs /config/plugins

EXPOSE 6123

VOLUME [ "/config" ]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "contenthive.main:app", "--host", "0.0.0.0", "--port", "6123"]