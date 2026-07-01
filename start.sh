#!/bin/bash
# BVR Nexus v2 — Quick Start Script with Secret Generation
set -e

echo "🚀 BVR Nexus v2 — Starting Full Stack..."
echo "==========================================="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "❌ Docker required"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "❌ Docker Compose required"; exit 1; }

# ── SECRET GENERATION ──
ENV_FILE=".env"

if [ ! -f "$ENV_FILE" ]; then
    echo "📋 Creating .env from template..."
    cp .env.example "$ENV_FILE"
fi

# Generate secrets for any field marked as GENERATE
generate_secret() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-32
}

update_secret() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=GENERATE" "$ENV_FILE"; then
        sed -i "s|^${key}=GENERATE|${key}=${value}|" "$ENV_FILE"
        echo "  🔑 Generated ${key}"
    elif ! grep -q "^${key}=" "$ENV_FILE"; then
        echo "${key}=${value}" >> "$ENV_FILE"
        echo "  🔑 Added ${key}"
    fi
}

echo "🔐 Generating secrets..."
update_secret "POSTGRES_PASSWORD" "$(generate_secret)"
update_secret "REDIS_PASSWORD" "$(generate_secret)"
update_secret "MINIO_ROOT_PASSWORD" "$(generate_secret)"
update_secret "KESTRA_DB_PASSWORD" "$(generate_secret)"
update_secret "VAULT_DEV_ROOT_TOKEN_ID" "$(generate_secret)"
update_secret "KEYCLOAK_ADMIN_PASSWORD" "$(generate_secret)"
update_secret "BVR_SERVICE_TOKEN" "$(generate_secret)"

echo "✅ Secrets configured in ${ENV_FILE}"

# ── START SERVICES ──

# Start data layer first
echo "📦 Starting data layer..."
docker compose up -d postgres redis minio

# Wait for PostgreSQL
echo "⏳ Waiting for PostgreSQL..."
until docker exec bvr-postgres pg_isready -U bvr -d bvr_nexus >/dev/null 2>&1; do
    sleep 2
done
echo "✅ PostgreSQL ready"

# Start application layer
echo "⚙️  Starting application layer..."
docker compose up -d bvr-api ai-gateway

# Start orchestration
echo "🎼 Starting orchestration..."
docker compose up -d kestra

# Start workers
echo "👷 Starting workers..."
docker compose up -d bvr-workers

# Start governance
echo "🛡️  Starting governance..."
docker compose up -d opa vault keycloak

# Start observability
echo "📊 Starting observability..."
docker compose up -d prometheus grafana jaeger loki

# Start ingress
echo "🌐 Starting ingress..."
docker compose up -d traefik

# Initialize MinIO
echo "📁 Initializing MinIO..."
docker compose up minio-init

# ── POST-STARTUP SETUP ──
echo ""
echo "⏳ Waiting for services to initialize (30s)..."
sleep 30

echo ""
echo "==========================================="
echo "✅ BVR Nexus v2 is starting up!"
echo "==========================================="
echo ""
echo "📋 Service URLs:"
echo "  BVR API Docs:   http://localhost:8000/docs"
echo "  Kestra UI:      http://localhost:8080"
echo "  Grafana:        http://localhost:3000  (admin/admin)"
echo "  Traefik Dash:   http://localhost:8082"
echo "  Vault:          http://localhost:8200"
echo "  Keycloak:       http://localhost:8081"
echo "  MinIO Console:  http://localhost:9001"
echo "  Jaeger:         http://localhost:16686"
echo "  OPA:            http://localhost:8181"
echo ""
echo "🔐 Security Setup (run these next):"
echo "  ./scripts/setup_vault.sh    # Initialize Vault production mode"
echo "  ./scripts/setup_keycloak.sh # Setup Keycloak realm"
echo ""
echo "🧪 Test: bvr status"
echo ""
