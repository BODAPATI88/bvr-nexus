#!/usr/bin/env bash
# Deploy public-site dist files to the Azure VM.
# Run from k8s-master after each new dist/ build is committed.
# Usage: bash scripts/deploy-public-site.sh [--ssh-key /path/to/key]
set -euo pipefail

AZURE_VM_IP="9.205.154.113"
AZURE_VM_USER="raviadmin"
WEBROOT="/var/www/bvrinfra"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$REPO_ROOT/public-site/dist"
SSH_KEY="${SSH_KEY:-}"

# Allow override via flag
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssh-key) SSH_KEY="$2"; shift 2 ;;
    --user)    AZURE_VM_USER="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ ! -d "$DIST_DIR" ]]; then
  echo "ERROR: dist/ not found at $DIST_DIR"
  exit 1
fi

# Build ssh options — omit -i if no key configured
SSH_OPTS="-o StrictHostKeyChecking=accept-new"
[[ -n "$SSH_KEY" && -f "$SSH_KEY" ]] && SSH_OPTS="$SSH_OPTS -i $SSH_KEY"

echo "==> Syncing $DIST_DIR to $AZURE_VM_USER@$AZURE_VM_IP:$WEBROOT ..."
rsync -avz --delete \
  -e "ssh $SSH_OPTS" \
  "$DIST_DIR/" \
  "$AZURE_VM_USER@$AZURE_VM_IP:$WEBROOT/"

echo "==> Fixing permissions on VM..."
ssh $SSH_OPTS "$AZURE_VM_USER@$AZURE_VM_IP" \
  "sudo chown -R www-data:www-data $WEBROOT && sudo chmod -R 755 $WEBROOT"

echo ""
echo "Deploy complete. https://bvrinfra.in is live."
