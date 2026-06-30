FROM python:3.12-slim

WORKDIR /app

COPY docker/ca-bundle.crt /usr/local/share/ca-certificates/proxy-ca.crt
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gcc git \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY bvr-sdk/ /app/bvr-sdk/
RUN pip install /app/bvr-sdk

COPY ai-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ai-gateway/main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
