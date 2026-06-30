FROM python:3.12-slim

WORKDIR /app

COPY docker/ca-bundle.crt /usr/local/share/ca-certificates/proxy-ca.crt
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gcc libpq-dev git \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy BVR SDK first so the file:// reference in requirements.txt resolves
COPY bvr-sdk/ /app/bvr-sdk/

COPY workers/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY workers/ ./workers/
COPY plugins/ ./plugins/
COPY contracts/ ./contracts/

COPY workers/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]
