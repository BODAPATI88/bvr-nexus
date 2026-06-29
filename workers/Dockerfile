FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends     gcc     libpq-dev     git     && rm -rf /var/lib/apt/lists/*

# Copy BVR SDK first (local dependency)
COPY bvr-sdk/ /app/bvr-sdk/
RUN pip install /app/bvr-sdk

# Copy workers
COPY workers/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY workers/ ./workers/
COPY plugins/ ./plugins/

# Default: run all workers via supervisor or similar
# For now, run a specific worker
COPY workers/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]
