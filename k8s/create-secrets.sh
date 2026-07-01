#!/usr/bin/env bash
# Creates the bvr-nexus-secrets k8s Secret from a local .env file.
# Run this ONCE on the cluster before ArgoCD syncs, or after rotating secrets.
# The Secret is intentionally excluded from ArgoCD management — it is never in git.
#
# Usage:
#   bash k8s/create-secrets.sh              # reads .env in current directory
#   bash k8s/create-secrets.sh /path/.env   # explicit path

set -euo pipefail

ENV_FILE="${1:-.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found."
  echo "Copy .env.example to .env and populate all values before running this script."
  exit 1
fi

# Load env vars without exporting to shell environment
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

NAMESPACE=bvr-nexus

echo "Creating namespace $NAMESPACE (if not exists)..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

echo "Creating bvr-nexus-secrets..."
kubectl create secret generic bvr-nexus-secrets \
  --namespace="$NAMESPACE" \
  --from-literal=POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
  --from-literal=REDIS_PASSWORD="${REDIS_PASSWORD:-}" \
  --from-literal=MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD}" \
  --from-literal=MINIO_KMS_SECRET_KEY="${MINIO_KMS_SECRET_KEY:-}" \
  --from-literal=VAULT_TOKEN="${VAULT_TOKEN}" \
  --from-literal=BVR_SERVICE_TOKEN="${BVR_SERVICE_TOKEN}" \
  --from-literal=KESTRA_ADMIN_USERNAME="${KESTRA_ADMIN_USERNAME:-admin}" \
  --from-literal=KESTRA_ADMIN_PASSWORD="${KESTRA_ADMIN_PASSWORD}" \
  --from-literal=KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD}" \
  --from-literal=GF_ADMIN_PASSWORD="${GF_ADMIN_PASSWORD}" \
  --from-literal=TRAEFIK_DASHBOARD_USERS="${TRAEFIK_DASHBOARD_USERS:-}" \
  --from-literal=ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
  --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
  --from-literal=KIMI_API_KEY="${KIMI_API_KEY:-}" \
  --from-literal=GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
  --from-literal=SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}" \
  --from-literal=ACME_EMAIL="${ACME_EMAIL:-admin@bvrinfra.in}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "Done. Verify with:"
echo "  kubectl get secret bvr-nexus-secrets -n bvr-nexus"
