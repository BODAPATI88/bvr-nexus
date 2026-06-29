#!/bin/bash
# Vault Production Setup Script
# Run this AFTER Vault container is running

set -e

echo "🔐 Initializing Vault (production mode)..."

# Initialize Vault with 5 key shares, 3 threshold
INIT_OUTPUT=$(docker exec bvr-vault vault operator init -key-shares=5 -key-threshold=3 -format=json)

# Extract unseal keys and root token
UNSEAL_KEY_1=$(echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[0]')
UNSEAL_KEY_2=$(echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[1]')
UNSEAL_KEY_3=$(echo "$INIT_OUTPUT" | jq -r '.unseal_keys_b64[2]')
ROOT_TOKEN=$(echo "$INIT_OUTPUT" | jq -r '.root_token')

# Save to secure location
cat > vault-init.json <<EOF
{
  "unseal_keys": ["$UNSEAL_KEY_1", "$UNSEAL_KEY_2", "$UNSEAL_KEY_3"],
  "root_token": "$ROOT_TOKEN"
}
EOF
chmod 600 vault-init.json

# Unseal Vault (need 3 keys)
echo "🔓 Unsealing Vault..."
docker exec bvr-vault vault operator unseal "$UNSEAL_KEY_1"
docker exec bvr-vault vault operator unseal "$UNSEAL_KEY_2"
docker exec bvr-vault vault operator unseal "$UNSEAL_KEY_3"

# Enable KV v2 secrets engine
echo "📦 Enabling KV v2..."
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" bvr-vault vault secrets enable -version=2 kv

# Enable transit encryption
echo "🔑 Enabling transit encryption..."
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" bvr-vault vault secrets enable transit

# Create encryption key for BVR
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" bvr-vault vault write -f transit/keys/bvr-master

echo ""
echo "✅ Vault initialized and configured"
echo "⚠️  IMPORTANT: Save vault-init.json securely and delete after setup"
echo "   Root Token: $ROOT_TOKEN"
echo ""
echo "To unseal after restart:"
echo "  docker exec bvr-vault vault operator unseal <key1>"
echo "  docker exec bvr-vault vault operator unseal <key2>"
echo "  docker exec bvr-vault vault operator unseal <key3>"
