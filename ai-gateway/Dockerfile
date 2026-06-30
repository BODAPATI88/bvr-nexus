FROM python:3.12-slim

WORKDIR /app

COPY docker/ca-bundle.crt /app/proxy-ca.crt
ENV PIP_CERT=/app/proxy-ca.crt

COPY bvr-sdk/ /app/bvr-sdk/
RUN pip install /app/bvr-sdk

COPY ai-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Append proxy CA to certifi's bundle so runtime HTTPS to AI providers trusts it
RUN python -c "import certifi; open(certifi.where(), 'a').write(open('/app/proxy-ca.crt').read())"

COPY ai-gateway/main.py .
COPY contracts/ ./contracts/
COPY plugins/ ./plugins/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
