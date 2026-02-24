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

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY contenthive ./contenthive

COPY entrypoint /entrypoint
RUN chmod +x /entrypoint

EXPOSE 6123

VOLUME /config

ENTRYPOINT [ "/entrypoint" ]