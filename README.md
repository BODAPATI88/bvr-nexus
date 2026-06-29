# BVR Nexus v2 — Revised Integrated Architecture

> **Kestra orchestrates. BVR API routes. Workers execute. AI Gateway abstracts.**  
> Built by integrating proven components. Your event-driven design is preserved.

---

## 🎯 What's Different from v1

| Issue in v1 | Fix in v2 |
|-------------|-----------|
| Kestra contained business logic | Kestra only orchestrates (HTTP calls) |
| Event Platform was replaced | Event Platform is the execution runtime |
| LangGraph was the center | LangGraph is a capability, not the center |
| Weaviate for vector search | PostgreSQL + pgvector (simpler ops) |
| Kafka for messaging | Redis Streams (sufficient for scale) |
| ClickHouse for analytics | PostgreSQL + Loki (sufficient) |
| Kong + Traefik overlap | Traefik only |
| No SDK | BVR SDK standardizes all workers |
| No AI Gateway | AI Gateway abstracts all LLM providers |
| No plugin system | Manifest-based auto-discovery |
| No platform registry | Central registry for everything |

---

## 🏗️ Architecture

```
Users (CLI / Web / VS Code / Slack)
    ↓
Traefik (Ingress + TLS)
    ↓
FastAPI Gateway (Auth, Validation, Rate Limit)
    ↓
┌─────────────────┬─────────────────┐
│                 │                 │
Kestra          BVR Event Bus     AI Gateway
(Orchestrate)   (Redis Streams)   (LLM Abstraction)
    │                 │                 │
    │         ┌──────┴──────┐          │
    │         │  Registry   │          │
    │         │  (Postgres) │          │
    │         └──────┬──────┘          │
    │                │                 │
    │         ┌──────┴──────┐          │
    │         │   Workers   │          │
    │         │  (Python)   │◄─────────┘
    │         └──────┬──────┘
    │                │
    └────────────────┘
                     │
              ┌──────┴──────┐
              │  Artifacts  │
              │   (MinIO)   │
              └─────────────┘
```

**Key Flow:**
1. User sends intent via CLI/Web/Slack
2. Traefik routes to FastAPI Gateway
3. Gateway validates auth, rate limits
4. Kestra receives webhook, builds execution graph
5. Kestra calls BVR API (`POST /api/v1/events`)
6. BVR API stores event, publishes to Redis Streams
7. Router reads from stream, looks up worker in Registry
8. Worker executes business logic (using BVR SDK)
9. Worker calls AI Gateway if LLM needed
10. Worker posts result back to BVR API
11. Kestra fetches result, continues graph
12. Artifact uploaded to MinIO
13. Notification sent

---

## 📦 Quick Start

### Prerequisites
- Docker Engine 24.0+
- Docker Compose v2.20+
- 8GB RAM minimum

### 1. Start the Platform
```bash
cd bvr-nexus
chmod +x start.sh
./start.sh
```

### 2. Verify Status
```bash
# Install CLI
pip install -e bvr-cli/

# Check all systems
bvr status
```

### 3. Run Your First Workflow
```bash
# Via CLI (emits event to BVR API)
bvr review https://github.com/example/repo --branch main

# Via API directly
curl -X POST http://localhost:8000/api/v1/events   -H "Content-Type: application/json"   -d '{
    "event_type": "review.repository",
    "payload": {"repo_url": "https://github.com/example/repo", "branch": "main"},
    "correlation_id": "manual-1",
    "source": "api"
  }'
```

### 4. Access Dashboards
| Service | URL | Role |
|---------|-----|------|
| BVR API Docs | http://localhost:8000/docs | API documentation |
| Kestra UI | http://localhost:8080 | Orchestration graphs |
| Grafana | http://localhost:3000 | Metrics & dashboards |
| Traefik | http://localhost:8082 | Ingress dashboard |
| Vault | http://localhost:8200 | Secrets |
| Keycloak | http://localhost:8081 | Auth management |
| MinIO | http://localhost:9001 | Artifacts |
| Jaeger | http://localhost:16686 | Distributed traces |
| OPA | http://localhost:8181 | Policy decisions |

---

## 📁 Project Structure

```
bvr-nexus/
├── docker-compose.yml              # Full stack (simplified)
├── README.md
├── start.sh
│
├── api/                            # FastAPI Gateway (YOUR APPLICATION)
│   ├── main.py                     # Event endpoints, registry CRUD
│   ├── requirements.txt
│   ├── Dockerfile
│   └── init.sql                    # DB schema + pgvector
│
├── bvr-sdk/                        # BVR SDK (pip install bvr-sdk)
│   ├── bvr_sdk/
│   │   ├── __init__.py             # Unified import
│   │   ├── events.py               # EventEnvelope, emit, subscribe
│   │   ├── auth.py                 # Token, permission, Vault secrets
│   │   ├── storage.py              # MinIO artifact operations
│   │   ├── ai.py                   # AI Gateway client + caching
│   │   ├── telemetry.py            # OpenTelemetry tracing
│   │   ├── retry.py                # Tenacity + circuit breaker
│   │   ├── policy.py               # OPA client
│   │   └── registry.py             # Worker registration, discovery
│   ├── setup.py
│   └── requirements.txt
│
├── workers/                        # BVR Workers (YOUR BUSINESS LOGIC)
│   ├── base.py                     # BaseWorker class
│   ├── review_worker.py            # Code analysis
│   ├── research_worker.py          # Topic synthesis
│   ├── achieve_worker.py           # Resume optimization
│   ├── requirements.txt
│   └── Dockerfile
│
├── plugins/                        # Plugin System (AUTO-DISCOVERY)
│   ├── ai/
│   │   ├── claude/
│   │   │   ├── manifest.yaml       # Plugin metadata
│   │   │   ├── schema.yaml         # Input/output contracts
│   │   │   ├── permissions.yaml    # Required permissions
│   │   │   ├── health.py           # Health check
│   │   │   └── worker.py           # Execution logic
│   │   ├── gpt/
│   │   └── ollama/
│   ├── devops/
│   │   ├── azure/
│   │   └── kubernetes/
│   ├── code/
│   │   └── github/
│   └── productivity/
│       └── slack/
│
├── kestra-workflows/               # Kestra Orchestration (NO BUSINESS LOGIC)
│   ├── review/
│   │   └── repository.yml          # HTTP calls to BVR API only
│   ├── research/
│   │   └── topic.yml
│   └── achieve/
│       └── resume-optimization.yml
│
├── contracts/                        # YAML Constitution
│   ├── workflow.yaml
│   ├── operation.yaml
│   ├── integration.yaml
│   ├── execution.yaml
│   ├── result.yaml
│   ├── artifact.yaml
│   ├── entity.yaml
│   └── goal.yaml
│
├── governance/                       # OPA Policies
│   └── rego/
│       ├── bvr.rego                  # Main RBAC
│       ├── cost.rego                 # Cost guardrails
│       └── data_residency.rego       # Compliance
│
├── gateway/                          # Traefik Config
│   └── traefik.yml
│
├── observability/                    # Prometheus + Grafana + Loki
│   ├── prometheus.yml
│   ├── loki-config.yml
│   └── dashboards/
│
└── bvr-cli/                          # Python CLI (Typer + Rich)
    ├── main.py
    ├── requirements.txt
    └── Dockerfile
```

---

## 🔧 Component Responsibilities

### Kestra (Orchestration Only)
**What it does:**
- Receives webhooks/triggers
- Builds execution DAG
- Calls BVR API via HTTP
- Waits for completion
- Handles retries, timeouts, approvals
- Sends notifications
- Enforces SLA

**What it does NOT do:**
- Analyze code
- Call LLMs directly
- Generate reports
- Any business logic

### BVR API (FastAPI Gateway)
**What it does:**
- Auth & rate limiting
- Event validation & routing
- Platform registry (workflows, workers, integrations, models, prompts)
- Cost tracking
- Result aggregation

### BVR Event Bus (Redis Streams)
**What it does:**
- Lightweight messaging
- Event persistence
- Consumer groups for workers
- Simple pub/sub

**Why not Kafka?**
- Redis Streams is sufficient for current scale
- One less infrastructure component
- Can upgrade to Kafka later without changing worker code

### BVR Workers (Python)
**What they do:**
- Execute all business logic
- Use BVR SDK for platform operations
- Call AI Gateway for LLM needs
- Generate artifacts
- Post results back

### AI Gateway (FastAPI)
**What it does:**
- Abstracts all LLM providers
- Automatic fallback (Claude → GPT → Kimi → Ollama)
- Cost tracking per call
- Response caching
- Route by capability

**Supported providers:**
- Claude (Anthropic)
- GPT (OpenAI)
- Kimi (Moonshot)
- Ollama (Local)

### PostgreSQL + pgvector
**What it stores:**
- Events & results
- Worker registry
- Integration registry
- Model registry
- Prompt registry
- Outcomes & metrics
- **Knowledge documents with vector embeddings**

**Why pgvector instead of Weaviate?**
- One database to manage
- One backup strategy
- One replication setup
- Fewer containers
- Upgrade to Weaviate only when you outgrow pgvector

---

## 🧩 Plugin System

Every integration is a plugin with:

```yaml
# manifest.yaml
id: github
name: GitHub
version: 2.0.0
type: code
capabilities:
  - clone_repository
  - create_pull_request
  - review_code
dependencies:
  - PyGithub>=2.3.0
config:
  token: "${GITHUB_TOKEN}"

# schema.yaml
input:
  type: object
  required: [action]
  properties:
    action:
      type: string
      enum: [clone, create_pr, review]

# permissions.yaml
permissions:
  - name: token
    required: true
    secret: true

# health.py
async def health_check(config: dict) -> dict:
    # Return {status: healthy|degraded|unhealthy}

# worker.py
async def execute(config: dict, inputs: dict) -> dict:
    # Business logic here
```

Plugins are auto-discovered at worker startup.

---

## 📊 Measurable Outcomes

| Outcome | Target | How Tracked |
|---------|--------|-------------|
| Fix critical issues | < 20 min | Kestra SLA + worker duration |
| Validated design | < 30 min | End-to-end workflow time |
| Decision-ready summary | < 10 min | BVR API response time |
| ATS score increase | +Y points | Pre/post worker comparison |
| Cost per execution | < $5 | AI Gateway cost tracking |
| Daily AI cost | < $50/user | Redis cost counters |
| Policy compliance | 100% | OPA on every event |

---

## 🛡️ Governance

### OPA Policies
- **bvr.rego**: RBAC, rate limits, target allowlists
- **cost.rego**: Max cost per execution ($5), max daily ($50), token limits
- **data_residency.rego**: Allowed regions, PII handling, classification

### Approval Flow
1. Event received
2. OPA evaluates policy
3. If approval required → Kestra Pause + notification
4. Human approves via UI
5. Worker executes

---

## 📈 Observability

All workers auto-instrument via BVR SDK:

```python
from bvr_sdk import trace_span, log_metric

@trace_span("my_worker.task")
async def handle(self, event):
    await log_metric("worker.tasks", 1, {"type": event.event_type})
```

**Stack:**
- OpenTelemetry → Jaeger (traces)
- Prometheus → Grafana (metrics)
- Loki → Grafana (logs)
- OpenCost → Grafana (cost)

---

## 🚀 Production Hardening

- [ ] Enable Traefik TLS (Let's Encrypt)
- [ ] Replace Vault dev mode with HA cluster
- [ ] Enable Keycloak production database
- [ ] Configure PostgreSQL replication
- [ ] Set up MinIO erasure coding
- [ ] Enable Redis Sentinel for HA
- [ ] Deploy workers on K8s with HPA
- [ ] Configure Prometheus remote write
- [ ] Set up PagerDuty alerting
- [ ] Rotate all default credentials
- [ ] Enable audit logging to S3
- [ ] Implement backup/restore procedures

---

## 📝 Key Design Decisions

1. **Kestra orchestrates, workers execute** — Separation of concerns
2. **Event Platform is the runtime** — Your original design preserved
3. **AI Gateway abstracts providers** — Fallback, cost tracking, caching
4. **pgvector over Weaviate** — Simpler ops, one database
5. **Redis Streams over Kafka** — Sufficient for scale, simpler
6. **Traefik only** — No Kong overlap
7. **BVR SDK standardizes everything** — Consistent worker interface
8. **Plugin system for extensibility** — Auto-discovery, no hard-coding
9. **Platform Registry for discoverability** — Everything registered
10. **Contracts as YAML Constitution** — Declarative over imperative

---

> **"If it doesn't reduce complexity, it doesn't belong."**  
> — BVR Prime Directive
