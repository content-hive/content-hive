FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1\
    TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install --with-deps chromium

COPY contenthive ./contenthive

EXPOSE 6123

CMD [ "uvicorn", "contenthive.main:app", "--host", "0.0.0.0", "--port", "6123" ]