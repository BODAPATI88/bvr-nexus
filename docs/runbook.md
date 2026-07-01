# BVR Nexus — Operations Runbook

---

## Health Checks

### Quick system health

```bash
make status
# or:
bvr status
```

### Per-service health

```bash
curl -s http://localhost:8000/health | jq .    # BVR API
curl -s http://localhost:8001/health | jq .    # AI Gateway
curl -s http://localhost:8080/health           # Kestra
```

### Check all containers

```bash
docker compose ps
```

Expected: all services `Up`, no restarts.

---

## Logs

```bash
make logs             # tail all services
make logs-api         # tail bvr-api only
make logs-workers     # tail bvr-workers only

# Ad-hoc:
docker compose logs -f bvr-api
docker compose logs -f ai-gateway --tail=100
docker compose logs --since=1h bvr-workers
```

Grafana/Loki log explorer: http://localhost:3000 → Explore → Loki datasource.

---

## Metrics and Traces

| Signal | URL | What to look for |
|--------|-----|-----------------|
| Grafana dashboards | http://localhost:3000 | Worker throughput, error rates, latency |
| Prometheus | http://localhost:9090 | Raw metrics, alert state |
| Jaeger traces | http://localhost:16686 | Request traces, span details |

Key metrics:
- `bvr_worker_tasks_total` — events processed per worker type
- `bvr_ai_gateway_calls_total` — LLM calls per provider
- `bvr_ai_gateway_cost_usd` — cumulative cost per provider
- `bvr_event_queue_depth` — Redis stream backlog

---

## Scaling Workers

Workers are stateless and scale horizontally. Each additional instance joins the `bvr-workers` consumer group.

**Docker Compose:**
```bash
docker compose up -d --scale bvr-workers=3
```

**Kubernetes:**
```bash
kubectl scale deployment bvr-workers --replicas=3 -n bvr-nexus
```

Workers self-register in the Platform Registry on startup via `BaseWorker.start()`. No manual registration required.

---

## Secret Rotation

### Rotate an API key

1. Update `.env` with the new key value
2. Restart the affected service:
   ```bash
   docker compose up -d --no-deps bvr-workers
   ```
3. For K8s: update the `bvr-nexus-secrets` Secret, then roll the deployment:
   ```bash
   bash k8s/create-secrets.sh
   kubectl rollout restart deployment/bvr-workers -n bvr-nexus
   ```

### Rotate the BVR service token

`BVR_SERVICE_TOKEN` authenticates worker-to-API calls.

1. Generate a new token: `openssl rand -hex 32`
2. Update `.env` → `BVR_SERVICE_TOKEN=<new>`
3. Restart both `bvr-api` and `bvr-workers`:
   ```bash
   docker compose up -d --no-deps bvr-api bvr-workers
   ```

### Vault token rotation

After `bash scripts/setup_vault.sh`, Vault issues a root token. Replace the development placeholder with this token:

```bash
# In .env:
VAULT_TOKEN=<vault-issued-token>

# Restart bvr-api:
docker compose up -d --no-deps bvr-api
```

---

## Backup and Restore

### Backup

```bash
make backup
# runs: pg_dump + MinIO snapshot
```

Manual PostgreSQL backup:
```bash
docker compose exec postgres pg_dump -U bvr bvr > backup_$(date +%Y%m%d).sql
```

Manual MinIO backup (via mc client):
```bash
mc mirror minio/bvr-artifacts ./backup/artifacts/
```

### Restore PostgreSQL

```bash
docker compose exec -T postgres psql -U bvr bvr < backup_20260101.sql
```

---

## Common Failures

### BVR API returns 503

1. Check PostgreSQL connectivity: `docker compose logs postgres`
2. Check Redis connectivity: `docker compose logs redis`
3. Verify `DATABASE_URL` and `REDIS_URL` env vars are set correctly

### Worker not processing events

1. Check worker logs: `make logs-workers`
2. Verify Redis stream has messages: `docker compose exec redis redis-cli XLEN bvr-events`
3. Check consumer group lag: `docker compose exec redis redis-cli XINFO GROUPS bvr-events`
4. If dead letter queue is filling up, check for repeated errors in worker logs

### AI Gateway returns 503

All providers in the fallback chain (Claude → GPT → Kimi → Ollama) failed.

1. Check API keys are set in `.env`
2. Check circuit breaker state: `docker compose logs ai-gateway | grep "circuit"`
3. Circuit breaker auto-recovers after 60 seconds — wait and retry
4. Confirm Ollama is running as last-resort fallback: `curl http://localhost:11434/api/tags`

### OPA policy denial

Events rejected by OPA appear in worker logs as `POLICY_DENIED`.

1. Check which policy denied: `docker compose logs bvr-workers | grep POLICY`
2. Review `governance/rego/` for the relevant policy
3. Run OPA tests to verify policy behavior: `opa test governance/rego/`

### Vault unsealed but token invalid

After a container restart, Vault requires unsealing:

```bash
docker compose exec vault vault operator unseal <unseal-key-1>
docker compose exec vault vault operator unseal <unseal-key-2>
docker compose exec vault vault operator unseal <unseal-key-3>
```

You need 3 of the 5 unseal keys generated during `setup_vault.sh`.

### Kestra not triggering workflows

1. Check Kestra UI: http://localhost:8080
2. Verify webhook URLs in Kestra flows match the BVR API host
3. Check BVR API auth: Kestra uses `BVR_SERVICE_TOKEN` for webhook calls
4. Review Kestra logs: `docker compose logs kestra`

### Redis stream memory pressure

If Redis memory is high:

1. Check stream length: `docker compose exec redis redis-cli XLEN bvr-events`
2. Trim old processed messages: `docker compose exec redis redis-cli XTRIM bvr-events MAXLEN 10000`
3. Increase Redis `maxmemory` in `docker-compose.yml` if needed

---

## Stopping and Restarting

```bash
make stop             # stop all containers, preserve volumes
make start            # restart
make clean            # DESTRUCTIVE: stop + delete all data volumes
```

To restart a single service:
```bash
docker compose restart bvr-api
docker compose up -d --no-deps --force-recreate ai-gateway
```

---

## Kubernetes Operations

```bash
# Check pod status
kubectl get pods -n bvr-nexus

# Tail logs
kubectl logs -f deployment/bvr-api -n bvr-nexus
kubectl logs -f deployment/bvr-workers -n bvr-nexus

# Restart a deployment
kubectl rollout restart deployment/bvr-api -n bvr-nexus

# Scale workers
kubectl scale deployment bvr-workers --replicas=5 -n bvr-nexus

# Check events (for crash diagnosis)
kubectl describe pod <pod-name> -n bvr-nexus
```
