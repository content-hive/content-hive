FROM python:3.12-slim

# Metadata
LABEL version="0.1.0" \
      description="Content Hive - A content parsing service" \
      maintainer="shaoxiaof@hotmail.com"

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install browsers
RUN playwright install --with-deps chromium

# Copy application code
COPY contenthive ./contenthive

# Port for the application
EXPOSE 6123

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:6123/health')"

CMD ["uvicorn", "contenthive.main:app", "--host", "0.0.0.0", "--port", "6123"]