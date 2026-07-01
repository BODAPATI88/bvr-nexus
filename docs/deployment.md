# BVR Nexus — Deployment Guide

---

## Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Docker Engine | 24.0+ | `docker version` to verify |
| Docker Compose | v2.20+ | `docker compose version` |
| RAM | 8 GB | 16 GB recommended for full stack |
| Disk | 20 GB free | For volumes, images, artifacts |
| CPU | 4 cores | 8 recommended |

---

## Local Deployment (Docker Compose)

### 1. Clone and configure environment

```bash
git clone https://github.com/bodapati88/bvr-nexus.git
cd bvr-nexus
cp .env.example .env
make secrets          # generates random values for GENERATE placeholders
```

Edit `.env` and populate the required external API keys:

```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
KIMI_API_KEY=...
GITHUB_TOKEN=ghp_...
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
```

### 2. Start the full stack

```bash
make start
# equivalent to: ./start.sh → docker compose up -d
```

This brings up all services in dependency order. First startup takes 3–5 minutes while images are pulled and databases are initialized.

### 3. Verify health

```bash
make status
# calls: bvr status (via bvr-cli)

# Manual health checks:
curl http://localhost:8000/health    # BVR API
curl http://localhost:8001/health    # AI Gateway
curl http://localhost:8080/health    # Kestra
```

### 4. Initialize governance services (first run only)

```bash
bash scripts/setup_vault.sh      # initializes Vault, stores secrets
bash scripts/setup_keycloak.sh   # creates BVR realm, client, roles
```

> **Note:** `make vault-setup` and `make keycloak-setup` are broken — they reference Python scripts that do not exist. Always run the shell scripts directly.

After `setup_vault.sh` completes, it prints unseal keys and a root token. **Store these externally** (e.g., a password manager). The container does not persist them.

---

## Service Ports

| Service | Port | URL |
|---------|------|-----|
| BVR API | 8000 | http://localhost:8000/docs |
| AI Gateway | 8001 | http://localhost:8001/v1/completions |
| Kestra UI | 8080 | http://localhost:8080 |
| Keycloak | 8081 | http://localhost:8081 |
| Traefik Dashboard | 8082 | http://localhost:8082 |
| Grafana | 3000 | http://localhost:3000 |
| MinIO Console | 9001 | http://localhost:9001 |
| Prometheus | 9090 | http://localhost:9090 |
| Jaeger | 16686 | http://localhost:16686 |
| Ollama | 11434 | http://localhost:11434 |

---

## Kubernetes Deployment

### Prerequisites

- `kubectl` configured for your cluster
- `helm` (optional, for operator-based components)
- Cluster with at least 8 CPU and 32 GB RAM across nodes

### 1. Create secrets

Populate a `.env` file with all required values, then:

```bash
bash k8s/create-secrets.sh
# Creates the bvr-nexus-secrets k8s Secret from .env
# The Secret is NOT in git — it is cluster-managed only
```

Verify:
```bash
kubectl get secret bvr-nexus-secrets -n bvr-nexus
```

### 2. Apply manifests in order

```bash
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-configmap.yaml
kubectl apply -f k8s/02-pvcs.yaml
kubectl apply -f k8s/03-postgres.yaml
kubectl apply -f k8s/03b-db-migrate.yaml
kubectl apply -f k8s/04-redis.yaml
kubectl apply -f k8s/05-minio.yaml
kubectl apply -f k8s/06-opa.yaml
kubectl apply -f k8s/07-vault.yaml
kubectl apply -f k8s/08-kestra.yaml
kubectl apply -f k8s/08b-keycloak.yaml
kubectl apply -f k8s/09-jaeger.yaml
kubectl apply -f k8s/10-bvr-api.yaml
kubectl apply -f k8s/11-ai-gateway.yaml
kubectl apply -f k8s/12-bvr-workers.yaml
kubectl apply -f k8s/13-ingressroute.yaml
kubectl apply -f k8s/14-prometheus.yaml
kubectl apply -f k8s/15-grafana.yaml
kubectl apply -f k8s/16-loki.yaml
kubectl apply -f k8s/17-traefik.yaml
kubectl apply -f k8s/18-redis-exporter.yaml
```

Or apply all at once (order is handled by readiness probes and init containers):

```bash
kubectl apply -f k8s/
```

### 3. Verify rollout

```bash
kubectl get pods -n bvr-nexus
kubectl rollout status deployment/bvr-api -n bvr-nexus
kubectl rollout status deployment/bvr-workers -n bvr-nexus
```

### 4. Initialize governance (first run)

```bash
# Port-forward to Vault
kubectl port-forward svc/vault 8200:8200 -n bvr-nexus

# Then run the setup script targeting the forwarded port
VAULT_ADDR=http://localhost:8200 bash scripts/setup_vault.sh
```

---

## Database Schema

The schema is initialized automatically on first startup via `api/init.sql`. This file is the authoritative schema definition.

For schema migrations on an existing deployment:

1. Add migration SQL to `api/init.sql` (idempotent — use `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`)
2. Rebuild and redeploy `bvr-api` — the lifespan handler re-runs the init SQL on startup
3. For K8s: apply the updated `k8s/03b-db-migrate.yaml` Job before rolling the API deployment

---

## Make Targets

```bash
make build            # Build all Docker images
make start            # Start full stack (docker compose up -d)
make stop             # Stop all services (preserves data volumes)
make clean            # Stop + delete all volumes (DESTRUCTIVE)
make logs             # Tail all logs
make logs-api         # Tail BVR API logs only
make logs-workers     # Tail worker logs only
make status           # bvr status health check
make lint             # ruff + black --check + mypy
make format           # ruff --fix + black (auto-format)
make security         # bandit + safety check
make backup           # pg_dump + MinIO snapshot
make secrets          # Generate GENERATE placeholders in .env
```

---

## TLS Configuration

Traefik handles TLS termination on port 443 with HTTP→HTTPS redirect. Configure certificates in `gateway/traefik.yml` or via ACME (Let's Encrypt) for production.

For local development, Traefik generates a self-signed certificate automatically.

---

## Hardcoded Development Credentials

`docker-compose.yml` contains hardcoded values for local development convenience. **These must be replaced before any shared or production deployment:**

| Location | Value | Replacement |
|----------|-------|-------------|
| `DATABASE_URL` in bvr-api/workers | `bvrsecret` | `${POSTGRES_PASSWORD}` |
| `minio-init` entrypoint | `bvradmin bvrsecret123` | env vars |
| Kestra `KESTRA_CONFIGURATION` | `accessKey: bvradmin` | env vars |
| `VAULT_TOKEN` in bvr-api | `bvr-root-token` | Vault-issued token |
| `MINIO_SECRET_KEY` | `bvrsecret123` | `${MINIO_ROOT_PASSWORD}` |
| Grafana | `GF_SECURITY_ADMIN_PASSWORD: admin` | `${GRAFANA_ADMIN_PASSWORD}` |

See the audit remediation checklist in `BVR_Nexus_v2_AUDIT_REPORT.md` for full details.
