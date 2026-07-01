# BVR Nexus — Activity Report
**Period:** 2026-06-29 to 2026-07-01 (48 hours)  
**Prepared:** 2026-07-01  
**Branch merged:** `claude/bvr-nexus-architecture-v8inv5` → `main` (PR #2)

---

## Executive Summary

Over 48 hours, BVR Nexus went from an initial codebase baseline to a fully operational Kubernetes deployment verified end-to-end. The session covered initial repository setup, Docker Compose hardening, GitHub Actions CI, Kubernetes GitOps via ArgoCD, and resolution of six production-class deployment bugs. The final state is a running k3s cluster with all platform services healthy and the `review.repository` workflow processing events to `completed` status.

---

## Timeline

### 2026-06-29 — Foundation

| Time (UTC) | Activity |
|---|---|
| 06:50 | Initial BVR Nexus codebase committed |
| 08:02 | Production baseline established |
| 10:27–10:48 | Product management structure initialized: vision, roadmap, backlog, Sprint 01 auth plan |
| 12:44–13:16 | Engineering governance docs: AI policy, Git workflow standards |
| 18:00–18:18 | GitHub Actions CI pipeline added; Gemini API connectivity test |
| 19:00 | `fix(api)`: database initialization consolidated into FastAPI `lifespan()` context manager (removed deprecated `@app.on_event("startup")`) |
| 19:27–19:32 | Auth audit merged; CI pipeline finalized |
| 22:54 | Event routing and webhook notification fixes; test coverage added |
| 23:34–23:35 | Provider/plugin ID mismatches fixed; echo AI stub added for e2e validation; `dump.rdb` added to `.gitignore` |

### 2026-06-30 — Docker Compose Hardening + K8s Deployment Start

| Time (UTC) | Activity |
|---|---|
| 03:22 | API smoke test added |
| 03:34 | Docker Compose stack hardened for reliable startup ordering |
| 04:00 | Three concurrent fixes: proxy CA cert via `PIP_CERT + certifi` patch; OPA healthcheck disabled; `dulwich` replaces subprocess git in review worker; workers post results back to API |
| 04:54 | Security hardening: dev vs production Docker Compose separation |
| 06:09 | Startup failure fixes from dev validation run |
| 12:44 (IST) | PR #1 merged to `main` |
| 11:40 (IST) | `CLAUDE.md` aligned with actual repository state |
| 19:04 | Observability wired: full log, metrics, and Grafana datasource pipeline |
| 22:13 | **Kubernetes Phase 1 manifests added** (`k8s/` directory) — namespace, configmaps, secrets script, postgres, redis, minio, OPA, Vault, Keycloak, Traefik, ai-gateway, bvr-api, bvr-workers, ArgoCD Application |
| 22:18 | Ollama removed from Phase 1 (deferred) |
| 22:41–22:45 | Traefik `IngressRoute` CRD not installed on cluster → replaced with standard `networking.k8s.io/v1 Ingress` |
| 22:59 | OPA `--ignore ".*"` flag added to prevent duplicate rule loading from ConfigMap hidden versioned directories |
| 23:22 | **DB race condition fixed**: ArgoCD PreSync db-migrate Job creates all 8 application tables before sync; `wait-for-postgres` initContainer added to bvr-api; `wait-for-api` initContainer added to bvr-workers |
| 23:46 | **Cascade explosion fixed** — 11,908 runaway events in seconds traced to `emit_event()` in worker error path; removed from `BaseWorker._handle_event()`; `.completed`/`.failed` filter added to SDK `subscribe()` |
| 23:55 | **Docker build fixed**: all three Dockerfiles hard-copied `docker/ca-bundle.crt` (gitignored); replaced with `ARG PROXY_CA=""` optional build argument |

### 2026-07-01 — Verification, Hardening, Merge

| Time (UTC) | Activity |
|---|---|
| 00:16 | ArgoCD Application `targetRevision` aligned to feature branch in git |
| 00:24 | **Redis PEL fix**: `subscribe()` changed to always ACK in `finally` block — unACK'd messages were accumulating in PEL on pod restart (`asyncio.CancelledError` bypasses `except Exception`) |
| 00:39 | `PYTHONUNBUFFERED=1` added to workers Dockerfile; `workers/__init__.py` created — background worker processes were buffering stdout, making `kubectl logs` appear silent during event processing |
| 00:41 | **Slack fix**: `review.repository` events were completing the full pipeline (clone → LLM → MinIO upload) but failing at the final Slack step due to placeholder webhook URL; made notification best-effort |
| 02:00+ | New workers image built and deployed; end-to-end test confirmed `status: completed` |
| ~02:55 | PR #2 created and merged to `main`; ArgoCD switched to track `main` |

---

## Bugs Found and Fixed

### 1. Database Race Condition (Critical)
**Symptom:** `bvr-api` started before postgres was ready; asyncpg pool creation failed silently; `app.state.db` was `None`; all registry calls returned 500.  
**Root cause:** No startup ordering between postgres and bvr-api; `INIT_SQL` never ran.  
**Fix:** ArgoCD PreSync Job (`k8s/03b-db-migrate.yaml`) creates all 8 tables via psql before any pod starts. `wait-for-postgres` initContainer loops `pg_isready` before uvicorn starts.

### 2. Event Cascade Explosion (Critical)
**Symptom:** Sending one `bvr.review` event produced 11,908 events in the Redis stream within seconds.  
**Root cause:** `BaseWorker._handle_event()` emitted `{event_type}.failed` back to the same Redis stream on every error. Other consumer groups picked up `.failed` events, failed to process them, emitted `.failed.failed`, and so on infinitely.  
**Fix:** Removed `emit_event()` from error path in `workers/base.py`. Added `endswith((".completed", ".failed"))` guard in `bvr-sdk/bvr_sdk/events.py` `subscribe()` as defense-in-depth.

### 3. Docker Build Failure (Blocking)
**Symptom:** `docker build` failed with `COPY docker/ca-bundle.crt: not found`.  
**Root cause:** All three Dockerfiles hard-copied `docker/ca-bundle.crt` which is in `.gitignore` (real proxy CA cert must never be committed).  
**Fix:** Replaced hard COPY with `ARG PROXY_CA=""` build argument. Cert is written only if the arg is non-empty. No cert = standard TLS behavior. Existing CI/CD unaffected.

### 4. OPA Duplicate Rule Error (Blocking)
**Symptom:** OPA refused to start: `multiple default rules data.bvr.allow found`.  
**Root cause:** Kubernetes ConfigMap mounts create hidden `..2026_xxx/` versioned symlink directories alongside the actual files. OPA loaded each `.rego` file twice.  
**Fix:** Added `--ignore ".*"` to OPA startup args to skip dotfile directories.

### 5. Redis PEL Buildup (Reliability)
**Symptom:** After pod restarts, events accumulated in the Redis Pending Entry List and were never acknowledged.  
**Root cause:** `subscribe()` only ACK'd on successful handler return. `asyncio.CancelledError` (raised by pod SIGTERM) is a `BaseException`, not caught by `except Exception`, so ACK never ran. Status is tracked in postgres, not Redis — no retry value in keeping messages pending.  
**Fix:** Moved `xack()` to `finally` block so it always runs regardless of handler outcome.

### 6. Slack Notification Blocking Event Completion (High)
**Symptom:** `review.repository` events returned `status: failed` even after full pipeline completion.  
**Root cause:** Slack notification step raised `HTTP 404` against placeholder webhook URL `https://hooks.slack.com/services/YOUR/WEBHOOK/URL`. Exception propagated up and failed the entire event.  
**Fix:** Slack step wrapped in `try/except` with URL presence check. Notification is best-effort; the event result is not affected by notification delivery.

---

## Verification Results

All tests run against live k3s cluster (k8s-master + k8s-worker1 + k8s-worker2):

| Check | Result |
|---|---|
| All pods `1/1 Running` | ✅ |
| 12 postgres tables present | ✅ |
| 3 workers registered (code-analyzer, topic-synthesizer, resume-optimizer) | ✅ |
| Redis stream stable (no cascade) | ✅ |
| `review.repository` event accepted by API | ✅ |
| Worker consumed event from Redis stream | ✅ |
| Repository cloned via dulwich (251 objects) | ✅ |
| AI Gateway called for `code_analysis` | ✅ |
| Report uploaded to MinIO | ✅ |
| Event status `completed` in postgres | ✅ |
| Repeated runs stable (test-001 through test-005) | ✅ |

---

## Repository State

**Commits merged to `main` in this period:** 40  
**PRs merged:** 2 (PR #1, PR #2)  
**Files changed (Phase 1 K8s + fixes):** 20+

### Key files added
```
k8s/
├── 00-namespace.yaml
├── 01-configmap.yaml
├── 02-secrets-template.yaml
├── 03-postgres.yaml
├── 03b-db-migrate.yaml      ← PreSync db-migrate Job (new)
├── 04-redis.yaml
├── 05-minio.yaml
├── 06-opa.yaml
├── 07-vault.yaml
├── 08-keycloak.yaml
├── 09-traefik.yaml
├── 10-bvr-api.yaml          ← wait-for-postgres initContainer added
├── 11-ai-gateway.yaml
├── 12-bvr-workers.yaml      ← wait-for-api initContainer added
└── create-secrets.sh
argocd/bvr-nexus-app.yaml
```

### Key files modified
```
workers/base.py              ← removed emit_event from error path
workers/review_worker.py     ← Slack best-effort
workers/Dockerfile           ← PYTHONUNBUFFERED=1, optional CA cert
workers/__init__.py          ← new (explicit package)
ai-gateway/Dockerfile        ← optional CA cert
api/Dockerfile               ← optional CA cert
bvr-sdk/bvr_sdk/events.py   ← cascade filter + ACK in finally
```

---

## What Remains

| Area | Status |
|---|---|
| Real API keys (Anthropic, OpenAI, GitHub, Slack) | Not set — echo AI stub in use |
| Test suite (`tests/` directory) | Planned — `make test` broken |
| `make vault-setup` / `make keycloak-setup` | Broken — call non-existent `.py` scripts |
| Hardcoded credentials in `docker-compose.yml` | 6 instances documented in CLAUDE.md |
| Web UI | Planned |
| VS Code extension | Planned |
| Slack bot | Planned |
| Log shipping to Loki | Planned (stdout only today) |
| OpenCost integration | Planned (Redis counters today) |
