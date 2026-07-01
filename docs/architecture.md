# BVR Nexus — Architecture

> **Prime Directive: "If it doesn't reduce complexity, it doesn't belong."**

---

## System Overview

BVR Nexus is a declarative workflow orchestration platform. It translates user intent (via CLI, Web, or Slack) into event-driven AI workflows executed by specialized workers, with full governance, cost tracking, and observability.

```
Users (CLI / Web / VS Code / Slack)
    ↓
Traefik            — Ingress, TLS termination, routing
    ↓
FastAPI Gateway    — Auth, rate limiting, validation, event API
    ↓
┌──────────────────┬──────────────────┐
│                  │                  │
Kestra             BVR Event Bus      AI Gateway
(Orchestrate)      (Redis Streams)    (LLM Abstraction)
    │                  │                  │
    │          ┌───────┴───────┐          │
    │          │   Registry    │          │
    │          │  (Postgres)   │          │
    │          └───────┬───────┘          │
    │                  │                  │
    │          ┌───────┴───────┐          │
    │          │   Workers     │◄─────────┘
    │          │  (Python)     │
    │          └───────┬───────┘
    │                  │
    └──────────────────┘
                       │
               ┌───────┴───────┐
               │  MinIO        │
               │ (Artifacts)   │
               └───────────────┘
```

---

## Seven-Layer Model

### L0 — User Interface
Entry points into the platform. All communicate exclusively through the FastAPI Gateway.

| Component | Status | Notes |
|-----------|--------|-------|
| BVR CLI | ✅ Built | `bvr-cli/main.py` — Typer + Rich |
| Web UI | Planned | FastAPI + React SPA |
| VS Code Extension | Planned | TypeScript |
| Slack Bot | Planned | Bolt + FastAPI |

### L1 — Orchestration (Kestra)
Kestra is the scheduler and SLA enforcer. It never contains business logic.

**Allowed in Kestra YAML:**
- Webhook triggers
- HTTP calls to `POST /api/v1/events`
- Wait / pause / timeout conditions
- Retry and SLA enforcement
- Approval gates
- Slack/email notifications

**Never in Kestra YAML:**
- Business logic
- LLM calls
- Data transforms
- File I/O

**Workflows:** `kestra-workflows/review/`, `kestra-workflows/research/`, `kestra-workflows/achieve/`

### L2 — Execution (BVR Event Platform)
The runtime core. All events pass through the Gateway and are dispatched via Redis Streams to Workers.

```
POST /api/v1/events
    → Validate (Pydantic) + Auth (JWT)
    → Store in PostgreSQL
    → Publish to Redis Stream "bvr-events"
    → Worker consumer group "bvr-workers" picks up
    → Worker executes via BVR SDK
    → Result stored → Gateway notifies Kestra
```

**Key constraint:** Workers only import from `bvr_sdk`, `workers.base`, and stdlib.

### L3 — Integration (Plugin System)
Every external integration is a self-describing plugin in `plugins/<category>/<name>/`.

Required files per plugin:
```
plugins/
└── <category>/
    └── <name>/
        ├── manifest.yaml     # identity, capabilities, version
        ├── schema.yaml       # typed input/output contract
        ├── permissions.yaml  # required secrets (via Vault)
        ├── health.py         # async health_check(config) → dict
        └── worker.py         # execute(config, inputs) → dict
                              # stream_execute(config, inputs) → AsyncGenerator
```

Plugins are auto-discovered at startup. Manifest SHA256 is verified before execution.

### L4 — Data & State

| Store | Use | Location |
|-------|-----|----------|
| PostgreSQL + pgvector | Events, registry, knowledge, audit | Primary state |
| Redis Streams | Event bus, consumer groups, cache | `bvr-events` stream |
| MinIO | Artifacts, reports, exports | SSE-S3 encrypted |
| Loki | Log aggregation | Container logs |

**Removed and must not return:** Weaviate, ClickHouse, Kafka, Kong.

### L5 — Governance

| Component | Role |
|-----------|------|
| OPA | Policy-as-code: RBAC, cost guardrails, data residency |
| Keycloak | SSO, RBAC, JWT issuance |
| Vault | Secret storage (KV v2), token management |
| `contracts/constitution.yaml` | Capability→provider mapping, cost limits |

Every event passes an OPA policy check before a worker handles it (`BaseWorker._handle_event()`).

### L6 — Observability
Auto-instrumented via BVR SDK decorators:

```python
@trace_span("worker.task_name")
async def handle(self, event: EventEnvelope):
    await log_metric("worker.tasks", 1, {"type": event.event_type})
```

| Signal | Tool | Dashboard |
|--------|------|-----------|
| Traces | Jaeger | http://localhost:16686 |
| Metrics | Prometheus → Grafana | http://localhost:3000 |
| Logs | Loki → Grafana | http://localhost:3000 |

---

## Data Flow

**Path A — CLI (direct):**
```
User intent → CLI → POST /api/v1/events (port 8000)
```

**Path B — Kestra-orchestrated:**
```
External trigger → Kestra webhook → Kestra DAG → POST /api/v1/events
```

Both paths converge at the Gateway:

```
1. Gateway validates auth + rate limits
2. Pydantic validates EventEnvelope → stored in PostgreSQL → published to Redis Stream
3. Workers read from Redis Stream (consumer group "bvr-workers")
4. Worker executes business logic using BVR SDK
5. Worker calls AI Gateway if LLM is needed
6. AI Gateway resolves provider via Capability Matcher → calls provider plugin
7. Provider fallback chain: Claude → GPT → Kimi → Ollama
8. Worker emits result event → Redis Stream
9. Gateway notifies Kestra via webhook callback (Path B only)
10. Artifact uploaded → MinIO
11. Notification → Slack / email
```

---

## AI Gateway Architecture

```
POST /v1/completions
    → Check circuit breaker (per provider)
    → Capability Matcher reads contracts/constitution.yaml
    → Try provider 1 (Claude): call plugin → track cost → return
    → On failure → try provider 2 (GPT)
    → On failure → try provider 3 (Kimi)
    → On failure → try provider 4 (Ollama, local)
    → All failed → HTTP 503
```

**Circuit breaker:** threshold=5 failures, recovery_timeout=60s, half-open probe on recovery.

**Cost guardrails:** OPA `cost.rego` enforces $5/execution and $50/user/day limits.

---

## Three Invariants

These constraints must never be violated:

1. **Kestra orchestrates.** It never runs business logic.
2. **Workers execute.** They only reach providers through the BVR SDK and AI Gateway.
3. **The AI Gateway abstracts all LLM providers.** No worker calls a provider API directly.

---

## Key Files

| File | Purpose |
|------|---------|
| `contracts/constitution.yaml` | Capability→provider mapping (source of truth) |
| `bvr-sdk/bvr_sdk/` | All platform operations for workers |
| `api/main.py` | FastAPI Gateway — auth, events, registry |
| `ai-gateway/main.py` | LLM abstraction, fallback, circuit breaker |
| `workers/base.py` | BaseWorker — event loop, OPA check, DLQ |
| `governance/rego/` | OPA policies — RBAC, cost, data residency |
| `api/init.sql` | Authoritative DB schema |
