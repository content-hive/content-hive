FROM python:3.12-slim

ARG APP_VERSION=0.1.0

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

# Copy application code
COPY contenthive ./contenthive

EXPOSE 6123

VOLUME /config

CMD ["uvicorn", "contenthive.main:app", "--host", "0.0.0.0", "--port", "6123"]