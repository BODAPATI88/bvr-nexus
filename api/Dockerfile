FROM python:3.12-slim

WORKDIR /app

# Point pip at the proxy CA cert so pip can verify SSL through the egress proxy.
# docker/ca-bundle.crt is a local-only file listed in .gitignore; in non-proxied
# environments an empty file is fine — pip ignores an empty cert bundle.
COPY docker/ca-bundle.crt /app/proxy-ca.crt
ENV PIP_CERT=/app/proxy-ca.crt

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/main.py .
COPY api/init.sql .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
