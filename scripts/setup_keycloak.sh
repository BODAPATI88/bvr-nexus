#!/bin/bash
# Keycloak Setup Script
# Creates BVR realm, client, and roles

set -e

KEYCLOAK_URL="http://localhost:8081"
ADMIN_USER="admin"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin}"

echo "🔑 Setting up Keycloak..."

# Wait for Keycloak to be ready
until curl -sf "${KEYCLOAK_URL}/health/ready" > /dev/null 2>&1; do
    echo "  Waiting for Keycloak..."
    sleep 5
done

# Get admin token
ADMIN_TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"     -H "Content-Type: application/x-www-form-urlencoded"     -d "username=${ADMIN_USER}"     -d "password=${ADMIN_PASS}"     -d "grant_type=password"     -d "client_id=admin-cli" | jq -r '.access_token')

if [ -z "$ADMIN_TOKEN" ] || [ "$ADMIN_TOKEN" = "null" ]; then
    echo "❌ Failed to get Keycloak admin token"
    exit 1
fi

# Create BVR realm
echo "  Creating BVR realm..."
curl -s -X POST "${KEYCLOAK_URL}/admin/realms"     -H "Authorization: Bearer ${ADMIN_TOKEN}"     -H "Content-Type: application/json"     -d '{
        "realm": "bvr",
        "enabled": true,
        "displayName": "BVR Nexus"
    }' || true

# Create roles
for role in bvr-admin bvr-operator bvr-viewer; do
    echo "  Creating role: $role"
    curl -s -X POST "${KEYCLOAK_URL}/admin/realms/bvr/roles"         -H "Authorization: Bearer ${ADMIN_TOKEN}"         -H "Content-Type: application/json"         -d "{"name": "$role", "description": "BVR $role"}" || true
done

# Create bvr-api client
echo "  Creating bvr-api client..."
curl -s -X POST "${KEYCLOAK_URL}/admin/realms/bvr/clients"     -H "Authorization: Bearer ${ADMIN_TOKEN}"     -H "Content-Type: application/json"     -d '{
        "clientId": "bvr-api",
        "name": "BVR API",
        "enabled": true,
        "clientAuthenticatorType": "client-secret",
        "secret": "bvr-api-secret-change-me",
        "redirectUris": ["http://localhost:8000/*"],
        "webOrigins": ["http://localhost:8000"],
        "publicClient": false,
        "protocol": "openid-connect"
    }' || true

echo "✅ Keycloak configured with BVR realm"
