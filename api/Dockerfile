FROM python:3.12-slim

WORKDIR /app

# Install proxy CA cert before pip so egress-proxied builds can reach PyPI.
# docker/ca-bundle.crt is an empty placeholder in the repo; override with the
# real cert in proxied CI/dev environments (see .gitignore).
COPY docker/ca-bundle.crt /usr/local/share/ca-certificates/proxy-ca.crt
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gcc libpq-dev \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/main.py .
COPY api/init.sql .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
