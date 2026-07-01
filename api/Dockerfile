FROM python:3.12-slim

WORKDIR /app

# Optional proxy CA certificate for corporate/proxy environments.
# Usage: docker build --build-arg PROXY_CA="$(cat docker/ca-bundle.crt)" ...
# Omit the arg (or leave it empty) for standard environments.
ARG PROXY_CA=""
RUN printf '%s' "${PROXY_CA}" > /app/proxy-ca.crt && \
    if [ -s /app/proxy-ca.crt ]; then \
        pip config set global.cert /app/proxy-ca.crt; \
    fi

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/main.py .
COPY api/init.sql .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
