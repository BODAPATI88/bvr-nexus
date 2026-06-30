FROM python:3.12-slim

WORKDIR /app

COPY docker/ca-bundle.crt /app/proxy-ca.crt
ENV PIP_CERT=/app/proxy-ca.crt

# Copy BVR SDK first so the file:// reference in requirements.txt resolves
COPY bvr-sdk/ /app/bvr-sdk/

COPY workers/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Append proxy CA to certifi's bundle so all runtime HTTPS (dulwich, httpx) trusts it
RUN python -c "import certifi; open(certifi.where(), 'a').write(open('/app/proxy-ca.crt').read())"

COPY workers/ ./workers/
COPY plugins/ ./plugins/
COPY contracts/ ./contracts/

COPY workers/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]
