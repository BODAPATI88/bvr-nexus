FROM python:3.12-slim

WORKDIR /app

# Optional proxy CA certificate for corporate/proxy environments.
# Usage: docker build --build-arg PROXY_CA="$(cat docker/ca-bundle.crt)" ...
# Omit the arg (or leave it empty) for standard environments.
ARG PROXY_CA=""
RUN printf '%s' "${PROXY_CA}" > /app/proxy-ca.crt && \
    if [ -s /app/proxy-ca.crt ]; then \
        pip config set global.cert /app/proxy-ca.crt && \
        python -c "import certifi; open(certifi.where(),'a').write(open('/app/proxy-ca.crt').read())" 2>/dev/null || true; \
    fi

COPY bvr-sdk/ /app/bvr-sdk/
RUN pip install /app/bvr-sdk

COPY ai-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Append proxy CA to certifi's bundle so runtime HTTPS to AI providers trusts it
RUN if [ -s /app/proxy-ca.crt ]; then \
        python -c "import certifi; open(certifi.where(),'a').write(open('/app/proxy-ca.crt').read())"; \
    fi

COPY ai-gateway/main.py .
COPY contracts/ ./contracts/
COPY plugins/ ./plugins/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
